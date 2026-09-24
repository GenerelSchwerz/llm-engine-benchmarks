#!/usr/bin/env python3
"""Install pinned public backend and tool sources from manifests/sources.json."""

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests/sources.json"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")


def run(*args: str) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args[:3])} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def destination(item: dict) -> Path:
    return ROOT / ("tools" if item["kind"] == "tool" else "sources") / item["id"]


def install(item: dict) -> None:
    target = destination(item)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        head = run("git", "-C", str(target), "rev-parse", "HEAD")
        dirty = run("git", "-C", str(target), "status", "--porcelain")
        if head != item["sha"] or dirty:
            raise RuntimeError(f"{target} exists but differs from the pin or has local changes")
        print(f"verified {item['id']} {head}")
        return

    url = f"https://github.com/{item['repo']}.git"
    with tempfile.TemporaryDirectory(prefix=f".{item['id']}-", dir=target.parent) as temporary:
        checkout = Path(temporary) / "checkout"
        run("git", "clone", "--filter=blob:none", "--single-branch", "--branch", item["branch"], url, str(checkout))
        try:
            run("git", "-C", str(checkout), "cat-file", "-e", f"{item['sha']}^{{commit}}")
        except RuntimeError:
            run("git", "-C", str(checkout), "fetch", "--filter=blob:none", "origin", item["sha"])
        run("git", "-C", str(checkout), "switch", "--detach", item["sha"])
        head = run("git", "-C", str(checkout), "rev-parse", "HEAD")
        if head != item["sha"]:
            raise RuntimeError(f"wrong revision for {item['id']}: {head}")
        checkout.rename(target)
    print(f"installed {item['id']} {head}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", help="install every listed source")
    selection.add_argument("--id", action="append", help="install one source ID; repeatable")
    args = parser.parse_args()
    data = json.loads(MANIFEST.read_text())
    if data.get("schema_version") != 1:
        parser.error("unsupported manifest schema_version")
    items = data["sources"]
    ids = set()
    for item in items:
        if (not ID.fullmatch(item["id"]) or not SHA.fullmatch(item["sha"])
                or item["kind"] not in {"backend", "tool"}
                or not item["repo"] or not item["branch"] or item["id"] in ids):
            parser.error(f"invalid source entry: {item}")
        ids.add(item["id"])
    if not args.all and not args.id:
        for item in items:
            print(f"{item['id']:22} {item['kind']:7} {item['repo']}:{item['branch']} @ {item['sha'][:12]}")
        print("Use --id NAME (repeatable) or --all to install.")
        return 0
    requested = set(ids if args.all else args.id)
    unknown = requested - ids
    if unknown:
        parser.error(f"unknown IDs: {', '.join(sorted(unknown))}")
    for item in items:
        if item["id"] in requested:
            install(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
