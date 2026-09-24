#!/usr/bin/env python3
"""Agent-facing, validated writes for human setup requests."""

import argparse
import json

from tui_data import get_request, save_engine, save_model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    show = sub.add_parser("show-request")
    show.add_argument("request_id")
    engine = sub.add_parser("add-engine")
    engine.add_argument("--name", default="")
    engine.add_argument("--type", required=True, choices=("git", "package", "container", "remote", "local"))
    engine.add_argument("--locator", required=True)
    engine.add_argument("--ref", default="")
    engine.add_argument("--notes", default="")
    engine.add_argument("--revision", default="")
    engine.add_argument("--installed-path", default="")
    model = sub.add_parser("add-model")
    model.add_argument("--name", default="")
    model.add_argument("--artifact", required=True)
    model.add_argument("--family", default="")
    model.add_argument("--context", default="")
    model.add_argument("--engine", action="append", default=[])
    model.add_argument("--notes", default="")
    args = parser.parse_args()
    try:
        if args.action == "show-request":
            print(json.dumps(get_request(args.request_id), indent=2))
        elif args.action == "add-engine":
            print(save_engine({"label": args.name, "type": args.type, "locator": args.locator,
                               "ref_hint": args.ref, "notes": args.notes,
                               "revision": args.revision, "installed_path": args.installed_path}))
        elif args.action == "add-model":
            print(save_model({"label": args.name, "artifact": args.artifact,
                              "family": args.family, "context": args.context,
                              "engine_ids": args.engine, "notes": args.notes}))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
