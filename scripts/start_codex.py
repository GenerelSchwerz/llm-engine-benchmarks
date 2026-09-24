#!/usr/bin/env python3
"""Start an interactive Codex session for one benchmark suite stage."""

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from source_manifest import ROOT
from suite_store import create_suite, show_suite, validate_suite
from tui_data import list_engines, list_models, migrate_old_files


def make_prompt(stage: str, suite_id: str, engines: list[str], models: list[str], check_updates: bool) -> str:
    selection = (
        ", ".join(engines) if engines else
        "the engines frozen in the suite plan" if stage == "run" else
        "only the engines the user selects for this suite"
    )
    model_selection = ", ".join(models) if models else "the models selected for the suite"
    intro = (
        f"Work on benchmark suite {suite_id!r} for {selection} and {model_selection}. "
        "Read AGENTS.md, RUNBOOK.md, manifests/matrix.md, and the selected engine guides. "
        "Read selected setup records with 'uv run scripts/suite_store.py show " + suite_id + "'. "
        "Follow the runbook's fan-out, coalescing, "
        "and single-runner handoff. Use research subagents when available; otherwise "
        "complete the reviews sequentially and say so. Record engine revisions with "
        "'uv run scripts/suite_store.py record-engine', model revisions and tokenizer with "
        "'record-model', and per-pair commands with 'record-packet'. These commands validate "
        "and write to SQLite; check every exit status. Finish preparation with "
        "'uv run scripts/suite_store.py freeze " + suite_id + "'. If validation rejects a "
        "record, fix it and do not claim the plan is frozen. Preserve existing work and "
        "report exact artifacts, unresolved inputs, and next steps. "
    )
    if not engines and stage == "prepare":
        intro += (
            "No engine IDs were supplied. Ask the user to select engines before any "
            "source review or update checks; do not process the whole catalog by default. "
        )
    update_instruction = (
        "Check tracking refs for selected Git engines and verify versions for selected "
        "non-Git engines. Review upstream changes only where a revision moved. Do not "
        "change manifest pins silently. "
        if check_updates else
        "Skip freshness checks for already pinned sources. Resolve exact revisions for "
        "new or unpinned sources, and hash local artifacts through record-model/record-engine. "
        "Reuse prior arguments only if the exact engine, model, tool, adapter, workload, "
        "and hardware inputs match a validated run; otherwise review the pinned local "
        "source and mark the command as a draft. "
    )
    stages = {
        "prepare": (
            "Prepare a new frozen suite revision. " + update_instruction +
            "Check local source pins, identify model details and tokenizer, return packets "
            "per model and method, review code "
            "only where prior validation cannot be reused, coalesce the packets, and record the "
            "plan and required model/hardware inputs. Do not build engines, run model "
            "benchmarks, or publish results in this stage."
        ),
        "run": (
            "Run the already frozen suite plan from SQLite with one execution agent per machine. "
            "Validate builds and model output, execute coherent-generation and "
            "llama-benchy tracks where supported, retain raw evidence, and report "
            "qualified results. If no complete frozen plan exists, prepare it first "
            "and identify missing inputs before measurement. Do not publish results."
        ),
    }
    return intro + stages[stage]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "run"), help="prepare commands or run a frozen suite")
    parser.add_argument("suite_id", help="name for a suite revision, for example qwen-sept-2026")
    parser.add_argument("--engine", action="append", default=[], help="engine ID to include; repeatable")
    parser.add_argument("--model", action="append", default=[], help="model setup ID to include; repeatable")
    updates = parser.add_mutually_exclusive_group()
    updates.add_argument("--check-updates", dest="check_updates", action="store_true",
                         help="check selected upstream refs and review changed revisions during prepare")
    updates.add_argument("--no-check-updates", dest="check_updates", action="store_false",
                         help="use local pins without upstream checks (default)")
    parser.set_defaults(check_updates=False)
    parser.add_argument("--dry-run", action="store_true", help="print the command and prompt without launching Codex")
    args = parser.parse_args()
    if not args.suite_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in args.suite_id):
        parser.error("suite_id must contain only letters, digits, hyphens, and underscores")
    migrate_old_files()
    known = {item["id"] for item in list_engines()}
    unknown = set(args.engine) - known
    if unknown:
        parser.error(f"unknown engine IDs: {', '.join(sorted(unknown))}")
    known_models = {item["id"] for item in list_models()}
    unknown_models = set(args.model) - known_models
    if unknown_models:
        parser.error(f"unknown model IDs: {', '.join(sorted(unknown_models))}")
    if args.stage == "run" and args.check_updates:
        parser.error("update checks belong to prepare; run uses the frozen suite plan")
    prompt = make_prompt(args.stage, args.suite_id, args.engine, args.model, args.check_updates)
    command = ["codex", "-C", str(ROOT), prompt]
    if args.dry_run:
        print("Command:", shlex.join(command[:3]), "<generated prompt>")
        print("\nPrompt:\n", prompt, sep="")
        return 0
    executable = shutil.which("codex")
    if executable is None:
        print("Codex CLI is not installed or not on PATH. See https://developers.openai.com/codex/cli/", file=sys.stderr)
        return 1
    try:
        if args.stage == "prepare":
            create_suite(args.suite_id, args.engine, args.model, args.check_updates)
        else:
            frozen = show_suite(args.suite_id)
            if frozen["suite"]["status"] != "frozen":
                raise ValueError("Suite is not frozen; finish preparation first")
            if args.engine and set(args.engine) != {x["engine_id"] for x in frozen["engines"]}:
                raise ValueError("Selected engines differ from the frozen suite")
            if args.model and set(args.model) != {x["model_id"] for x in frozen["models"]}:
                raise ValueError("Selected models differ from the frozen suite")
            validate_suite(args.suite_id)
    except ValueError as exc:
        parser.error(str(exc))
    return subprocess.call([executable, *command[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
