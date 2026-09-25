#!/usr/bin/env python3
"""Store editable run setups and immutable instructions for launched runs."""

import argparse
import json
import math
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from suite_store import SUITE_ID, show_suite
from tui_data import DB, ROOT, connect

ARM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


@contextmanager
def database(path: Path = DB):
    with connect(path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS run_setups (
                id TEXT PRIMARY KEY,
                suite_id TEXT NOT NULL,
                name TEXT NOT NULL,
                vram_ceiling_gib REAL,
                description TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS run_instances (
                id TEXT PRIMARY KEY,
                suite_id TEXT NOT NULL,
                setup_id TEXT,
                name TEXT NOT NULL,
                vram_ceiling_gib REAL,
                description TEXT NOT NULL,
                output_dir TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS run_memory_checks (
                run_id TEXT NOT NULL,
                engine_id TEXT NOT NULL,
                arm TEXT NOT NULL,
                peak_total_mib REAL NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('within_ceiling','exceeded','no_ceiling')),
                checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(run_id, engine_id, arm)
            );
        """)
        yield db


def _ceiling(value: float | str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("VRAM ceiling must be a positive GiB number") from exc
    if not math.isfinite(number) or number <= 0 or number > 1024:
        raise ValueError("VRAM ceiling must be greater than 0 and at most 1024 GiB")
    return number


def save_setup(suite_id: str, name: str, vram_ceiling_gib: float | str | None = None,
               description: str = "", setup_id: str | None = None, path: Path = DB) -> str:
    if not SUITE_ID.fullmatch(suite_id):
        raise ValueError("Choose a suite with a safe ID")
    show_suite(suite_id, path)
    name = name.strip()
    if not name or len(name) > 120:
        raise ValueError("Run setup name must contain 1 to 120 characters")
    if not isinstance(description, str) or len(description) > 10000:
        raise ValueError("Run description must be at most 10,000 characters")
    ceiling = _ceiling(vram_ceiling_gib)
    with database(path) as db:
        if setup_id:
            existing = db.execute("SELECT suite_id FROM run_setups WHERE id=?", (setup_id,)).fetchone()
            if not existing or existing["suite_id"] != suite_id:
                raise ValueError("Run setup does not belong to this suite")
            db.execute("UPDATE run_setups SET name=?, vram_ceiling_gib=?, description=?, "
                       "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (name, ceiling, description, setup_id))
        else:
            setup_id = uuid.uuid4().hex[:12]
            db.execute("INSERT INTO run_setups(id,suite_id,name,vram_ceiling_gib,description) "
                       "VALUES (?,?,?,?,?)", (setup_id, suite_id, name, ceiling, description))
    return setup_id


def list_setups(suite_id: str, path: Path = DB) -> list[dict]:
    with database(path) as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM run_setups WHERE suite_id=? ORDER BY updated_at DESC, name COLLATE NOCASE, id",
            (suite_id,))]


def show_setup(setup_id: str, path: Path = DB) -> dict:
    with database(path) as db:
        row = db.execute("SELECT * FROM run_setups WHERE id=?", (setup_id,)).fetchone()
    if not row:
        raise ValueError(f"Unknown run setup {setup_id}")
    return dict(row)


def clone_setup(setup_id: str, name: str | None = None, path: Path = DB) -> str:
    source = show_setup(setup_id, path)
    return save_setup(source["suite_id"], name or f"{source['name'][:115]} copy",
                      source["vram_ceiling_gib"], source["description"], path=path)


def delete_setup(setup_id: str, path: Path = DB) -> None:
    with database(path) as db:
        if db.execute("DELETE FROM run_setups WHERE id=?", (setup_id,)).rowcount != 1:
            raise ValueError(f"Unknown run setup {setup_id}")


def create_run(suite_id: str, setup_id: str | None = None, path: Path = DB) -> dict:
    suite = show_suite(suite_id, path)
    if suite["suite"]["status"] != "frozen":
        raise ValueError("Freeze the suite before launching a run")
    setup = show_setup(setup_id, path) if setup_id else None
    if setup and setup["suite_id"] != suite_id:
        raise ValueError("Run setup does not belong to this suite")
    run_id = f"run-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:10]}"
    output_dir = ROOT / "results" / suite_id / run_id
    if output_dir.exists():
        raise ValueError(f"Run output already exists: {output_dir}")
    with database(path) as db:
        db.execute("INSERT INTO run_instances(id,suite_id,setup_id,name,vram_ceiling_gib,description,output_dir) "
                   "VALUES (?,?,?,?,?,?,?)", (run_id, suite_id, setup_id,
                   setup["name"] if setup else "Default run",
                   setup["vram_ceiling_gib"] if setup else None,
                   setup["description"] if setup else "", str(output_dir)))
    return show_run(run_id, path)


def show_run(run_id: str, path: Path = DB) -> dict:
    with database(path) as db:
        row = db.execute("SELECT * FROM run_instances WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise ValueError(f"Unknown run {run_id}")
    return dict(row)


def list_runs(suite_id: str, path: Path = DB) -> list[dict]:
    with database(path) as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM run_instances WHERE suite_id=? ORDER BY created_at DESC, id DESC",
            (suite_id,))]


def record_peak(run_id: str, engine_id: str, arm: str, peak_total_mib: float,
                path: Path = DB) -> dict:
    run = show_run(run_id, path)
    suite = show_suite(run["suite_id"], path)
    if engine_id not in {row["engine_id"] for row in suite["engines"]}:
        raise ValueError("Engine is not selected for this run's suite")
    if not ARM_ID.fullmatch(arm):
        raise ValueError("Arm needs a safe nonempty name")
    try:
        peak = float(peak_total_mib)
    except (TypeError, ValueError) as exc:
        raise ValueError("Peak GPU memory must be a nonnegative MiB number") from exc
    if not math.isfinite(peak) or peak < 0:
        raise ValueError("Peak GPU memory must be a nonnegative MiB number")
    ceiling = run["vram_ceiling_gib"]
    status = ("no_ceiling" if ceiling is None else
              "within_ceiling" if peak <= ceiling * 1024 else "exceeded")
    with database(path) as db:
        if db.execute("SELECT 1 FROM run_memory_checks WHERE run_id=? AND engine_id=? AND arm=?",
                      (run_id, engine_id, arm)).fetchone():
            raise ValueError("Peak already recorded for this run, engine, and arm")
        db.execute("INSERT INTO run_memory_checks(run_id,engine_id,arm,peak_total_mib,status) "
                   "VALUES (?,?,?,?,?)", (run_id, engine_id, arm, peak, status))
    return {"run_id": run_id, "engine_id": engine_id, "arm": arm,
            "peak_total_mib": peak, "ceiling_gib": ceiling, "status": status}


def list_peaks(run_id: str, path: Path = DB) -> list[dict]:
    show_run(run_id, path)
    with database(path) as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM run_memory_checks WHERE run_id=? ORDER BY engine_id,arm", (run_id,))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action, argument in (("list-setups", "suite"), ("show-setup", "setup_id"),
                             ("clone-setup", "setup_id"), ("delete-setup", "setup_id"),
                             ("list-runs", "suite"), ("show-run", "run_id"),
                             ("list-peaks", "run_id")):
        sub.add_parser(action).add_argument(argument)
    save = sub.add_parser("save-setup")
    save.add_argument("suite")
    save.add_argument("--name", required=True)
    save.add_argument("--vram-ceiling-gib", type=float)
    save.add_argument("--description", default="")
    save.add_argument("--setup-id")
    launch = sub.add_parser("create-run")
    launch.add_argument("suite")
    launch.add_argument("--setup-id")
    peak = sub.add_parser("record-peak")
    peak.add_argument("run_id")
    peak.add_argument("engine_id")
    peak.add_argument("arm")
    peak.add_argument("--peak-total-mib", type=float, required=True)
    args = parser.parse_args()
    try:
        if args.action == "list-setups":
            result = list_setups(args.suite)
        elif args.action == "show-setup":
            result = show_setup(args.setup_id)
        elif args.action == "clone-setup":
            result = {"id": clone_setup(args.setup_id)}
        elif args.action == "delete-setup":
            delete_setup(args.setup_id)
            result = {"deleted": args.setup_id}
        elif args.action == "list-runs":
            result = list_runs(args.suite)
        elif args.action == "show-run":
            result = show_run(args.run_id)
        elif args.action == "list-peaks":
            result = list_peaks(args.run_id)
        elif args.action == "record-peak":
            result = record_peak(args.run_id, args.engine_id, args.arm, args.peak_total_mib)
        elif args.action == "save-setup":
            result = {"id": save_setup(args.suite, args.name, args.vram_ceiling_gib,
                                       args.description, args.setup_id)}
        else:
            result = create_run(args.suite, args.setup_id)
        print(json.dumps(result, indent=2))
        if args.action == "record-peak" and result["status"] == "exceeded":
            return 1
    except (ValueError, sqlite3.Error, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
