#!/usr/bin/env python3
"""Index private run artifacts and validate agent-reviewed findings."""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

from source_manifest import ROOT

PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
SUMMARY_FILES = ("benchy-qualified-summary.json", "benchy-run-summary.json", "run-summary.json")


def run_dir(key: str, root: Path = ROOT) -> Path:
    parts = key.split("/")
    if len(parts) != 2 or any(not PART.fullmatch(part) or part in {".", ".."} for part in parts):
        raise ValueError("Use a run key in the form SUITE/RUN")
    base = (root / "results").resolve()
    target = base.joinpath(*parts)
    if target.exists() and (target.is_symlink() or target.resolve() != target):
        raise ValueError("Run directory must be a real directory under results/")
    return target


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def summary_for(directory: Path) -> tuple[str | None, dict]:
    for name in SUMMARY_FILES:
        path = directory / name
        if path.is_file() and not path.is_symlink():
            return name, read_json(path)
    return None, {}


def list_results(root: Path = ROOT) -> list[dict]:
    base = root / "results"
    if not base.is_dir():
        return []
    rows = []
    for suite in base.iterdir():
        if not suite.is_dir() or suite.is_symlink() or not PART.fullmatch(suite.name):
            continue
        for directory in suite.iterdir():
            if not directory.is_dir() or directory.is_symlink() or not PART.fullmatch(directory.name):
                continue
            key = f"{suite.name}/{directory.name}"
            try:
                name, data = summary_for(directory)
            except (OSError, ValueError, json.JSONDecodeError):
                name, data = "invalid summary", {}
            status = (data.get("benchy_status") or data.get("status") or
                      ("in progress" if not name else "summary saved"))
            rows.append({"key": key, "status": str(status), "summary_file": name,
                         "mtime": directory.stat().st_mtime})
    return sorted(rows, key=lambda row: row["mtime"], reverse=True)


def show_result(key: str, root: Path = ROOT) -> dict:
    directory = run_dir(key, root)
    if not directory.is_dir():
        raise ValueError(f"Unknown result {key}")
    name, data = summary_for(directory)
    return {"key": key, "directory": str(directory), "summary_file": name, "summary": data,
            "findings_saved": (directory / "findings.json").is_file()}


def _text_list(value: object, label: str, maximum: int = 20) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum or any(
        not isinstance(item, str) or not item.strip() or len(item) > 1000 for item in value
    ):
        raise ValueError(f"{label} must be a list of up to {maximum} nonempty strings")
    return [item.strip() for item in value]


def validate_findings(key: str, data: dict, root: Path = ROOT) -> dict:
    directory = run_dir(key, root)
    if not directory.is_dir():
        raise ValueError(f"Unknown result {key}")
    if not isinstance(data, dict) or set(data) != {"summary", "highlights", "limitations", "artifacts"}:
        raise ValueError("Findings need summary, highlights, limitations, and artifacts")
    summary = data["summary"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2000:
        raise ValueError("Findings summary must contain 1 to 2,000 characters")
    highlights = _text_list(data["highlights"], "highlights")
    limitations = _text_list(data["limitations"], "limitations")
    artifacts = _text_list(data["artifacts"], "artifacts", 50)
    for item in artifacts:
        path = Path(item)
        if path.is_absolute() or ".." in path.parts or not (directory / path).is_file():
            raise ValueError(f"Artifact must be an existing file within this run: {item}")
        if not (directory / path).resolve().is_relative_to(directory.resolve()):
            raise ValueError(f"Artifact escapes this run: {item}")
    return {"summary": summary.strip(), "highlights": highlights,
            "limitations": limitations, "artifacts": artifacts}


def record_findings(key: str, data: dict, root: Path = ROOT) -> Path:
    validated = validate_findings(key, data, root)
    directory = run_dir(key, root)
    with tempfile.NamedTemporaryFile("w", dir=directory, prefix=".findings-", suffix=".json",
                                     delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(validated, stream, indent=2)
        stream.write("\n")
    try:
        os.replace(temporary, directory / "findings.json")
    finally:
        temporary.unlink(missing_ok=True)
    return directory / "findings.json"


def pull_findings(key: str, root: Path = ROOT) -> dict:
    result = show_result(key, root)
    directory = Path(result["directory"])
    saved = directory / "findings.json"
    if saved.is_file():
        return {"source": "reviewed findings", **validate_findings(key, read_json(saved), root)}
    data = result["summary"]
    runs = data.get("runs", [])
    if not isinstance(runs, list):
        runs = []
    complete = sum(isinstance(row, dict) and row.get("status") == "complete" for row in runs)
    highlights = []
    for row in runs:
        if not isinstance(row, dict) or row.get("status") != "complete":
            continue
        shape = next((s for s in row.get("shapes", []) if isinstance(s, dict) and s.get("depth") == 0), None)
        if shape and isinstance(shape.get("decode_tps_median"), (int, float)):
            highlights.append(f"{row.get('engine')} / {row.get('arm')} / concurrency {row.get('concurrency')}: "
                              f"{shape['decode_tps_median']:.2f} decode tok/s median (depth 0)")
    limitations = [x for x in data.get("qualified_limitations", []) if isinstance(x, str)]
    if not result["summary_file"]:
        return {"source": "none", "summary": "No recognized run summary yet.",
                "highlights": [], "limitations": [], "artifacts": []}
    return {"source": result["summary_file"],
            "summary": f"{complete}/{len(runs)} benchmark configurations complete" if runs else
                       f"Summary available in {result['summary_file']}",
            "highlights": highlights, "limitations": limitations,
            "artifacts": [result["summary_file"]]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("key")
    pull = sub.add_parser("pull-findings")
    pull.add_argument("key")
    record = sub.add_parser("record-findings")
    record.add_argument("key")
    record.add_argument("json_file", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "list":
            value = list_results()
        elif args.action == "show":
            value = show_result(args.key)
        elif args.action == "pull-findings":
            value = pull_findings(args.key)
        else:
            value = {"saved": str(record_findings(args.key, read_json(args.json_file)))}
        print(json.dumps(value, indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
