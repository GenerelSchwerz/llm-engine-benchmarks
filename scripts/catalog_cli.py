#!/usr/bin/env python3
"""Agent-facing, validated writes for human setup requests."""

import argparse
import json

from tui_data import attach_request_result, get_request, save_engine, save_model


def check_request_target(request_id: str | None, kind: str) -> None:
    if request_id is None:
        return
    request = get_request(request_id)
    if request["kind"] != kind or request["status"] != "pending":
        raise ValueError(f"Request must be a pending {kind} setup")


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
    engine.add_argument("--request-id")
    model = sub.add_parser("add-model")
    model.add_argument("--name", default="")
    model.add_argument("--artifact", required=True)
    model.add_argument("--family", default="")
    model.add_argument("--context", default="")
    model.add_argument("--engine", action="append", default=[])
    model.add_argument("--notes", default="")
    model.add_argument("--request-id")
    attach = sub.add_parser("attach-result")
    attach.add_argument("request_id")
    attach.add_argument("result_id")
    args = parser.parse_args()
    try:
        if args.action == "show-request":
            print(json.dumps(get_request(args.request_id), indent=2))
        elif args.action == "add-engine":
            check_request_target(args.request_id, "engine")
            ident = save_engine({"label": args.name, "type": args.type, "locator": args.locator,
                               "ref_hint": args.ref, "notes": args.notes,
                               "revision": args.revision, "installed_path": args.installed_path})
            if args.request_id:
                attach_request_result(args.request_id, ident)
            print(ident)
        elif args.action == "add-model":
            check_request_target(args.request_id, "model")
            ident = save_model({"label": args.name, "artifact": args.artifact,
                              "family": args.family, "context": args.context,
                              "engine_ids": args.engine, "notes": args.notes})
            if args.request_id:
                attach_request_result(args.request_id, ident)
            print(ident)
        elif args.action == "attach-result":
            attach_request_result(args.request_id, args.result_id)
            print(args.result_id)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
