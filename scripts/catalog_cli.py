#!/usr/bin/env python3
"""Agent-facing, validated writes for human setup requests."""

import argparse
import json

from source_manifest import ROOT
from tui_data import (
    attach_request_result, get_request, list_engines, list_models,
    remove_for_request, save_engine, save_model,
    signal_request_complete, update_builtin_engine,
)


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
    sub.add_parser("list-engines")
    sub.add_parser("list-models")
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
    existing = sub.add_parser("use-existing")
    existing.add_argument("request_id")
    existing.add_argument("result_id")
    finish = sub.add_parser("finish-request")
    finish.add_argument("request_id")
    finish.add_argument("--message", required=True)
    update_engine = sub.add_parser("update-engine")
    update_engine.add_argument("id")
    update_engine.add_argument("--request-id", required=True)
    for flag in ("name", "type", "locator", "ref", "notes", "revision", "installed-path"):
        update_engine.add_argument(f"--{flag}")
    update_model = sub.add_parser("update-model")
    update_model.add_argument("id")
    update_model.add_argument("--request-id", required=True)
    for flag in ("name", "artifact", "family", "context", "notes"):
        update_model.add_argument(f"--{flag}")
    update_model.add_argument("--engine", action="append")
    for action in ("remove-engine", "remove-model"):
        remove = sub.add_parser(action)
        remove.add_argument("id")
        remove.add_argument("--request-id", required=True)
        remove.add_argument("--delete-install", action="store_true")
        remove.add_argument("--confirm-path", default="")
    args = parser.parse_args()
    try:
        if args.action == "show-request":
            print(json.dumps(get_request(args.request_id), indent=2))
        elif args.action == "list-engines":
            print(json.dumps(list_engines(), indent=2))
        elif args.action == "list-models":
            print(json.dumps(list_models(), indent=2))
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
        elif args.action in {"attach-result", "use-existing"}:
            attach_request_result(args.request_id, args.result_id)
            print(args.result_id)
        elif args.action == "finish-request":
            signal_request_complete(args.request_id, args.message)
            print(args.request_id)
        elif args.action == "update-engine":
            check_request_target(args.request_id, "engine")
            old = next((x for x in list_engines() if x["id"] == args.id), None)
            if old is None:
                raise ValueError("Unknown engine ID")
            if old["built_in"]:
                if any(getattr(args, name) is not None for name in ("name", "type", "locator", "notes")):
                    raise ValueError("Built-in overrides can change only revision, installed path, and ref")
                ident = update_builtin_engine(
                    args.id, args.revision or old["revision"],
                    args.installed_path or old["installed_path"] or str(ROOT / "sources" / args.id),
                    args.ref if args.ref is not None else old["ref_hint"])
            else:
                item = {"id": args.id, "label": args.name if args.name is not None else old["label"],
                        "type": args.type if args.type is not None else old["type"],
                        "locator": args.locator if args.locator is not None else old["locator"],
                        "ref_hint": args.ref if args.ref is not None else old["ref_hint"],
                        "notes": args.notes if args.notes is not None else old["notes"],
                        "revision": args.revision if args.revision is not None else old["revision"],
                        "installed_path": args.installed_path if args.installed_path is not None else old["installed_path"]}
                ident = save_engine(item)
            attach_request_result(args.request_id, ident)
            print(ident)
        elif args.action == "update-model":
            check_request_target(args.request_id, "model")
            old = next((x for x in list_models() if x["id"] == args.id), None)
            if old is None:
                raise ValueError("Unknown model ID")
            item = {"id": args.id, "label": args.name if args.name is not None else old["label"],
                    "artifact": args.artifact if args.artifact is not None else old["artifact"],
                    "family": args.family if args.family is not None else old["family"],
                    "context": args.context if args.context is not None else old["context"],
                    "engine_ids": args.engine if args.engine is not None else old["engine_ids"],
                    "notes": args.notes if args.notes is not None else old["notes"]}
            ident = save_model(item)
            attach_request_result(args.request_id, ident)
            print(ident)
        elif args.action in {"remove-engine", "remove-model"}:
            kind = args.action.split("-")[1]
            remove_for_request(kind, args.id, args.request_id,
                               delete_install=args.delete_install, confirm_path=args.confirm_path)
            print(args.id)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
