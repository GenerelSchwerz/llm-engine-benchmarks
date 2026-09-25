#!/usr/bin/env python3
"""Validated SQLite handoff between benchmark preparation and execution agents."""

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from tui_data import DB, ROOT, connect, list_engines, list_models

SUITE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
GIT_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
METHODS = ("coherent", "benchy")


@contextmanager
def database(path: Path = DB) -> Iterator[sqlite3.Connection]:
    with connect(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS suites (
            id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('draft','frozen')),
            check_updates INTEGER NOT NULL CHECK(check_updates IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS suite_engines (
            suite_id TEXT NOT NULL, engine_id TEXT NOT NULL, revision TEXT,
            setup_json TEXT NOT NULL, installed_path TEXT,
            PRIMARY KEY(suite_id, engine_id), FOREIGN KEY(suite_id) REFERENCES suites(id)
        );
        CREATE TABLE IF NOT EXISTS suite_models (
            suite_id TEXT NOT NULL, model_id TEXT NOT NULL, revision TEXT,
            artifact_hash TEXT, tokenizer TEXT, setup_json TEXT NOT NULL,
            PRIMARY KEY(suite_id, model_id), FOREIGN KEY(suite_id) REFERENCES suites(id)
        );
        CREATE TABLE IF NOT EXISTS packets (
            suite_id TEXT NOT NULL, engine_id TEXT NOT NULL, model_id TEXT NOT NULL,
            method TEXT NOT NULL CHECK(method IN ('coherent','benchy')),
            support TEXT NOT NULL CHECK(support IN ('supported','unavailable')),
            command_json TEXT, reason TEXT, tuning_rationale TEXT, memory_target TEXT,
            PRIMARY KEY(suite_id, engine_id, model_id, method)
        );
        CREATE TABLE IF NOT EXISTS suite_preparation_signals (
            suite_id TEXT PRIMARY KEY REFERENCES suites(id),
            message TEXT NOT NULL,
            completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(suite_engines)")}
        if "installed_path" not in columns:
            db.execute("ALTER TABLE suite_engines ADD COLUMN installed_path TEXT")
        yield db


def require_draft(db: sqlite3.Connection, suite: str) -> None:
    row = db.execute("SELECT status FROM suites WHERE id=?", (suite,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown suite {suite}; run prepare first")
    if row["status"] != "draft":
        raise ValueError(f"Suite {suite} is frozen; create a new suite ID for changes")


def create_suite(suite: str, engines: list[str], models: list[str],
                 check_updates: bool, path: Path = DB) -> None:
    if not SUITE_ID.fullmatch(suite) or not engines or not models:
        raise ValueError("A suite needs a safe name, at least one engine, and at least one model")
    known_engines = {x["id"]: x for x in list_engines(path)}
    known_models = {x["id"]: x for x in list_models(path)}
    if set(engines) - known_engines.keys() or set(models) - known_models.keys():
        raise ValueError("Suite references an unknown engine or model")
    with database(path) as db:
        existing = db.execute("SELECT status, check_updates FROM suites WHERE id=?", (suite,)).fetchone()
        if existing and existing["status"] == "frozen":
            raise ValueError("Suite is frozen; use a new suite ID")
        if existing:
            if existing["check_updates"] != int(check_updates):
                raise ValueError("Draft update-check mode differs; use a new suite ID")
            previous_engines = {r["engine_id"] for r in db.execute("SELECT engine_id FROM suite_engines WHERE suite_id=?", (suite,))}
            previous_models = {r["model_id"] for r in db.execute("SELECT model_id FROM suite_models WHERE suite_id=?", (suite,))}
            if previous_engines != set(engines) or previous_models != set(models):
                raise ValueError("Draft selection already exists; use a new suite ID to change it")
            return
        db.execute("INSERT INTO suites VALUES (?,?,?)", (suite, "draft", int(check_updates)))
        db.executemany("INSERT INTO suite_engines(suite_id,engine_id,setup_json) VALUES (?,?,?)",
                       [(suite, x, json.dumps(known_engines[x])) for x in dict.fromkeys(engines)])
        db.executemany("INSERT INTO suite_models(suite_id,model_id,setup_json) VALUES (?,?,?)",
                       [(suite, x, json.dumps(known_models[x])) for x in dict.fromkeys(models)])


def hash_artifact(artifact: str) -> str | None:
    path = Path(artifact).expanduser()
    if not path.exists():
        return None
    if not path.is_file() and not path.is_dir():
        raise ValueError(f"Cannot hash artifact {artifact}")
    digest = hashlib.sha256()
    files = [path] if path.is_file() else sorted(x for x in path.rglob("*") if x.is_file())
    if not files:
        raise ValueError(f"Artifact directory has no files: {artifact}")
    for entry in files:
        digest.update(str(entry.relative_to(path) if path.is_dir() else entry.name).encode())
        digest.update(b"\0")
        with entry.open("rb") as handle:
            for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def record_engine(suite: str, ident: str, revision: str | None = None,
                  path: Path = DB, installed_path: str | None = None) -> str:
    with database(path) as db:
        row = db.execute("SELECT setup_json FROM suite_engines WHERE suite_id=? AND engine_id=?", (suite, ident)).fetchone()
    if row is None:
        raise ValueError(f"Engine {ident} is not selected for this suite")
    item = json.loads(row["setup_json"])
    if item["type"] == "local":
        revision = hash_artifact(item["locator"])
        if revision is None:
            raise ValueError("Local engine executable must exist before recording")
    elif item["type"] == "git":
        revision = revision or item.get("revision") or item.get("source", {}).get("revision")
        if not revision or not GIT_SHA.fullmatch(revision):
            raise ValueError("Git engine needs an exact 40-character commit SHA")
        checkout_value = installed_path or item.get("installed_path") or (
            ROOT / "sources" / ident if item["built_in"] else None
        )
        if not checkout_value:
            raise ValueError("Git engine needs an installed checkout path")
        checkout = Path(checkout_value).expanduser()
        if not checkout.is_dir():
            raise ValueError("Git engine needs an installed checkout path")
        head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=False)
        if head.returncode or head.stdout.strip() != revision:
            raise ValueError("Installed Git checkout does not match the recorded revision")
        installed_path = str(checkout)
    elif item["type"] == "container":
        revision = revision or item.get("revision") or item["locator"].rpartition("@sha256:")[2]
        if not re.fullmatch(r"[0-9a-fA-F]{64}", revision or ""):
            raise ValueError("Container engine needs an exact image SHA256")
    elif not revision and not item.get("revision"):
        raise ValueError("Package or remote engine needs an exact version")
    else:
        revision = revision or item["revision"]
    with database(path) as db:
        require_draft(db, suite)
        if not db.execute("SELECT 1 FROM suite_engines WHERE suite_id=? AND engine_id=?", (suite, ident)).fetchone():
            raise ValueError("Engine is not selected for this suite")
        db.execute("UPDATE suite_engines SET revision=?, installed_path=? WHERE suite_id=? AND engine_id=?",
                   (revision, installed_path, suite, ident))
    return revision


def record_model(suite: str, ident: str, revision: str | None = None,
                 tokenizer: str | None = None, path: Path = DB) -> str:
    with database(path) as db:
        row = db.execute("SELECT setup_json FROM suite_models WHERE suite_id=? AND model_id=?", (suite, ident)).fetchone()
    if row is None:
        raise ValueError(f"Model {ident} is not selected for this suite")
    item = json.loads(row["setup_json"])
    artifact_hash = hash_artifact(item["artifact"])
    if artifact_hash is None and not revision:
        raise ValueError("Model is not local; provide an exact service or artifact revision")
    with database(path) as db:
        require_draft(db, suite)
        if not db.execute("SELECT 1 FROM suite_models WHERE suite_id=? AND model_id=?", (suite, ident)).fetchone():
            raise ValueError("Model is not selected for this suite")
        db.execute("UPDATE suite_models SET revision=?, artifact_hash=?, tokenizer=? WHERE suite_id=? AND model_id=?",
                   (revision, artifact_hash, tokenizer, suite, ident))
    return artifact_hash or revision or ""


def record_packet(suite: str, packet: dict, path: Path = DB) -> None:
    required = {"engine_id", "model_id", "method", "support"}
    if not isinstance(packet, dict) or not required <= packet.keys() or packet["method"] not in METHODS:
        raise ValueError("Packet needs engine_id, model_id, method, and support")
    if packet["support"] not in {"supported", "unavailable"}:
        raise ValueError("Packet support must be supported or unavailable")
    command = packet.get("command")
    if packet["support"] == "supported":
        if not isinstance(command, (list, dict)) or not command:
            raise ValueError("Supported packet needs a full command list or request object")
        if not packet.get("tuning_rationale") or not packet.get("memory_target"):
            raise ValueError("Supported packet needs tuning_rationale and memory_target")
    elif not packet.get("reason"):
        raise ValueError("Unavailable packet needs a reason")
    with database(path) as db:
        require_draft(db, suite)
        for table, field in (("suite_engines", "engine_id"), ("suite_models", "model_id")):
            if not db.execute(f"SELECT 1 FROM {table} WHERE suite_id=? AND {field}=?",
                              (suite, packet[field])).fetchone():
                raise ValueError(f"{packet[field]} is not selected for this suite")
        db.execute(
            "INSERT INTO packets VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(suite_id,engine_id,model_id,method) "
            "DO UPDATE SET support=excluded.support, command_json=excluded.command_json, "
            "reason=excluded.reason, tuning_rationale=excluded.tuning_rationale, memory_target=excluded.memory_target",
            (suite, packet["engine_id"], packet["model_id"], packet["method"], packet["support"],
             json.dumps(command) if command else None, packet.get("reason"),
             packet.get("tuning_rationale"), packet.get("memory_target")),
        )


def validate_suite(suite: str, path: Path = DB) -> None:
    with database(path) as db:
        if not db.execute("SELECT 1 FROM suites WHERE id=?", (suite,)).fetchone():
            raise ValueError(f"Unknown suite {suite}")
        engines = list(db.execute("SELECT * FROM suite_engines WHERE suite_id=?", (suite,)))
        models = list(db.execute("SELECT * FROM suite_models WHERE suite_id=?", (suite,)))
        packets = {(x["engine_id"], x["model_id"], x["method"]): x
                   for x in db.execute("SELECT * FROM packets WHERE suite_id=?", (suite,))}
    missing = []
    for engine in engines:
        if not engine["revision"]:
            missing.append(f"engine revision: {engine['engine_id']}")
        elif json.loads(engine["setup_json"])["type"] == "git":
            checkout = engine["installed_path"]
            head = (subprocess.run(["git", "-C", checkout, "rev-parse", "HEAD"],
                                   capture_output=True, text=True, check=False)
                    if checkout else None)
            if head is None or head.returncode or head.stdout.strip() != engine["revision"]:
                missing.append(f"engine checkout changed: {engine['engine_id']}")
        elif json.loads(engine["setup_json"])["type"] == "local":
            current = hash_artifact(json.loads(engine["setup_json"])["locator"])
            if current != engine["revision"]:
                missing.append(f"engine artifact changed: {engine['engine_id']}")
    for model in models:
        if not model["artifact_hash"] and not model["revision"]:
            missing.append(f"model hash/revision: {model['model_id']}")
        elif model["artifact_hash"]:
            current = hash_artifact(json.loads(model["setup_json"])["artifact"])
            if current != model["artifact_hash"]:
                missing.append(f"model artifact changed: {model['model_id']}")
    for engine in engines:
        for model in models:
            for method in METHODS:
                packet = packets.get((engine["engine_id"], model["model_id"], method))
                if packet is None:
                    missing.append(f"packet: {engine['engine_id']}/{model['model_id']}/{method}")
                elif method == "benchy" and packet["support"] == "supported" and not model["tokenizer"]:
                    missing.append(f"tokenizer: {model['model_id']}")
    if missing:
        raise ValueError("Suite is incomplete:\n  " + "\n  ".join(missing))


def freeze_suite(suite: str, path: Path = DB) -> None:
    validate_suite(suite, path)
    with database(path) as db:
        require_draft(db, suite)
        db.execute("UPDATE suites SET status='frozen' WHERE id=?", (suite,))


def finish_preparation(suite: str, message: str, path: Path = DB) -> None:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("A concise preparation summary is required")
    with database(path) as db:
        row = db.execute("SELECT status FROM suites WHERE id=?", (suite,)).fetchone()
        if row is None or row["status"] != "frozen":
            raise ValueError("Freeze the validated suite before marking preparation complete")
        db.execute("INSERT INTO suite_preparation_signals(suite_id,message) VALUES (?,?) "
                   "ON CONFLICT(suite_id) DO UPDATE SET message=excluded.message, "
                   "completed_at=CURRENT_TIMESTAMP", (suite, message.strip()))


def preparation_signal(suite: str, path: Path = DB) -> dict | None:
    with database(path) as db:
        row = db.execute("SELECT message, completed_at FROM suite_preparation_signals WHERE suite_id=?",
                         (suite,)).fetchone()
    return dict(row) if row else None


def show_suite(suite: str, path: Path = DB) -> dict:
    with database(path) as db:
        row = db.execute("SELECT * FROM suites WHERE id=?", (suite,)).fetchone()
        if not row:
            raise ValueError(f"Unknown suite {suite}")
        return {
            "suite": dict(row),
            "engines": [dict(x) | {"setup": json.loads(x["setup_json"])}
                        for x in db.execute("SELECT * FROM suite_engines WHERE suite_id=?", (suite,))],
            "models": [dict(x) | {"setup": json.loads(x["setup_json"])}
                       for x in db.execute("SELECT * FROM suite_models WHERE suite_id=?", (suite,))],
            "packets": [dict(x) for x in db.execute("SELECT * FROM packets WHERE suite_id=?", (suite,))],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("show", "validate", "freeze"):
        sub.add_parser(name).add_argument("suite")
    finish = sub.add_parser("finish-prepare")
    finish.add_argument("suite")
    finish.add_argument("--message", required=True)
    engine = sub.add_parser("record-engine")
    engine.add_argument("suite")
    engine.add_argument("engine_id")
    engine.add_argument("--revision")
    engine.add_argument("--installed-path")
    model = sub.add_parser("record-model")
    model.add_argument("suite")
    model.add_argument("model_id")
    model.add_argument("--revision")
    model.add_argument("--tokenizer")
    packet = sub.add_parser("record-packet")
    packet.add_argument("suite")
    packet.add_argument("json_file", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "show":
            print(json.dumps(show_suite(args.suite), indent=2))
        elif args.action == "validate":
            validate_suite(args.suite)
            print("Suite valid")
        elif args.action == "freeze":
            freeze_suite(args.suite)
            print("Suite frozen")
        elif args.action == "finish-prepare":
            finish_preparation(args.suite, args.message)
            print("Preparation complete")
        elif args.action == "record-engine":
            print(record_engine(args.suite, args.engine_id, args.revision,
                                installed_path=args.installed_path))
        elif args.action == "record-model":
            print(record_model(args.suite, args.model_id, args.revision, args.tokenizer))
        else:
            record_packet(args.suite, json.loads(args.json_file.read_text()))
            print("Packet saved")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
