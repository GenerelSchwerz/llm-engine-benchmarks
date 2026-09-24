#!/usr/bin/env python3
"""Read-only check of pinned source clones and optional tracking branches."""

import argparse
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(
    r"^\| `(?P<id>[^`]+)` \| \[`[^`]+`\]"
    r"\(https://github\.com/(?P<repo>[^)]+)/tree/(?P<branch>[^)]+)\)"
    r" \| `(?P<sha>[0-9a-f]{40})` \|"
)


def command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=30, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", action="store_true", help="read tracking heads with git ls-remote")
    args = parser.parse_args()

    entries = []
    for line in (ROOT / "manifests/forks.md").read_text().splitlines():
        match = ROW.match(line)
        if not match:
            continue
        item = match.groupdict()
        source = ROOT / "sources" / item["id"]
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
