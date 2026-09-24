#!/usr/bin/env python3
"""Read-only check of installed Git pins and optional remote refs."""

import argparse
import json
import subprocess

from source_manifest import destination, load_sources


def command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=30, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", action="store_true", help="check Git tracking refs with git ls-remote")
    args = parser.parse_args()
    entries = []
    for listed in load_sources():
        item = dict(listed)
        source = item["source"]
        item["local_path"] = str(destination(item))
        if source["type"] != "git":
            item["local_status"] = "manual_verification_required"
            if args.remote:
                item["remote_status"] = "manual_verification_required"
            entries.append(item)
            continue
        target = destination(item)
        if not target.is_dir():
            item["local_status"] = "missing"
        else:
            head = command("git", "-C", str(target), "rev-parse", "HEAD")
            dirt = command("git", "-C", str(target), "status", "--porcelain")
            item["local_head"] = head.stdout.strip() if head.returncode == 0 else None
            item["dirty"] = bool(dirt.stdout.strip()) if dirt.returncode == 0 else None
            item["local_status"] = (
                "pinned" if item["local_head"] == source["revision"] and item["dirty"] is False
                else "drift_or_dirty"
            )
        if args.remote:
            ref = source["ref"] if source["ref"].startswith("refs/") else f"refs/heads/{source['ref']}"
            remote = command("git", "ls-remote", source["url"], ref)
            item["remote_head"] = remote.stdout.split()[0] if remote.returncode == 0 and remote.stdout.strip() else None
            item["remote_status"] = (
                "error" if remote.returncode != 0 else
                "missing" if item["remote_head"] is None else
                "unchanged" if item["remote_head"] == source["revision"] else "moved"
            )
        entries.append(item)
    print(json.dumps({"sources": entries}, indent=2))
    return 0 if all(e["local_status"] in {"pinned", "manual_verification_required"} for e in entries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
