#!/usr/bin/env python3
"""List sources or install pinned Git engines and tools from the editable manifest."""

import argparse
import subprocess
import tempfile
from pathlib import Path

from source_manifest import destination, load_sources


def run(*args: str) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args[:3])} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def install(item: dict) -> None:
    source = item["source"]
    if source["type"] != "git":
        print(f"manual {item['id']}: {item['install_notes']}")
        return
    target = destination(item)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        head = run("git", "-C", str(target), "rev-parse", "HEAD")
        dirty = run("git", "-C", str(target), "status", "--porcelain")
        if head != source["revision"] or dirty:
            raise RuntimeError(f"{target} exists but differs from the pin or has local changes")
        print(f"verified {item['id']} {head}")
        return

    with tempfile.TemporaryDirectory(prefix=f".{item['id']}-", dir=target.parent) as temporary:
        checkout = Path(temporary) / "checkout"
        run("git", "clone", "--filter=blob:none", "--single-branch", "--branch", source["ref"], source["url"], str(checkout))
        try:
            run("git", "-C", str(checkout), "cat-file", "-e", f"{source['revision']}^{{commit}}")
        except RuntimeError:
            run("git", "-C", str(checkout), "fetch", "--filter=blob:none", "origin", source["revision"])
        run("git", "-C", str(checkout), "switch", "--detach", source["revision"])
        head = run("git", "-C", str(checkout), "rev-parse", "HEAD")
        if head != source["revision"]:
            raise RuntimeError(f"wrong revision for {item['id']}: {head}")
        checkout.rename(target)
    print(f"installed {item['id']} {head}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", help="install every listed source")
    selection.add_argument("--id", action="append", help="install one source ID; repeatable")
    args = parser.parse_args()
    items = load_sources()
    ids = {item["id"] for item in items}
    if not args.all and not args.id:
        for item in items:
            source = item["source"]
            label = source.get("url", source.get("image", source.get("name", source.get("model", "see install_notes"))))
            revision = source.get("revision", source.get("version", "manual"))
            print(f"{item['id']:22} {item['kind']:6} {source['type']:9} {label} @ {revision[:12]}")
        print("Use --id NAME (repeatable) or --all. Non-Git entries print install instructions.")
        return 0
    requested = ids if args.all else set(args.id)
    unknown = requested - ids
    if unknown:
        parser.error(f"unknown IDs: {', '.join(sorted(unknown))}")
    for item in items:
        if item["id"] in requested:
            install(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
