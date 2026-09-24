#!/usr/bin/env python3
"""Read-only check of pinned source clones and optional tracking branches."""

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=30, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", action="store_true", help="read tracking heads with git ls-remote")
    args = parser.parse_args()

    entries = []
    source_list = json.loads((ROOT / "manifests/sources.json").read_text())["sources"]
    for listed in source_list:
        item = dict(listed)
        source = ROOT / ("tools" if item["kind"] == "tool" else "sources") / item["id"]
        item["source"] = str(source)
        if not source.is_dir():
            item["local_status"] = "missing"
        else:
            head = command("git", "-C", str(source), "rev-parse", "HEAD")
            dirt = command("git", "-C", str(source), "status", "--porcelain")
            item["local_head"] = head.stdout.strip() if head.returncode == 0 else None
            item["dirty"] = bool(dirt.stdout.strip()) if dirt.returncode == 0 else None
            item["local_status"] = (
                "pinned" if item["local_head"] == item["sha"] and item["dirty"] is False
                else "drift_or_dirty"
            )
        if args.remote:
            url = f'https://github.com/{item["repo"]}.git'
            ref = f'refs/heads/{item["branch"]}'
            remote = command("git", "ls-remote", url, ref)
            item["remote_head"] = (
                remote.stdout.split()[0] if remote.returncode == 0 and remote.stdout.strip() else None
            )
            item["remote_status"] = (
                "error" if remote.returncode != 0 else
                "missing" if item["remote_head"] is None else
                "unchanged" if item["remote_head"] == item["sha"] else "moved"
            )
        entries.append(item)

    print(json.dumps({"sources": entries}, indent=2))
    return 0 if entries and all(e["local_status"] == "pinned" for e in entries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
