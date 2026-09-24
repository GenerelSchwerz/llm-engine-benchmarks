#!/usr/bin/env python3
"""Start an interactive Codex session for one benchmark suite stage."""

import argparse
import os
import shlex
import shutil
import sys
from pathlib import Path

from source_manifest import ROOT, load_sources


def make_prompt(stage: str, suite_id: str, engines: list[str]) -> str:
    selection = ", ".join(engines) if engines else "the engines selected in manifests/sources.json"
    intro = (
        f"Work on benchmark suite {suite_id!r} for {selection}. "
        "Read AGENTS.md, RUNBOOK.md, manifests/sources.json, manifests/matrix.md, "
        "and the relevant engine guides. Follow the runbook's fan-out, coalescing, "
        "and single-runner handoff. Use research subagents when available; otherwise "
        "complete the reviews sequentially and say so. Preserve existing work and "
        "report exact artifacts, unresolved inputs, and next steps. "
    )
    stages = {
        "prepare": (
            "Prepare a new frozen suite revision: check sources, review changed engine "
            "arguments per model and method, coalesce command packets, and record the "
            "plan and required model/hardware inputs. Do not build engines, run model "
            "benchmarks, or publish results in this stage."
        ),
        "run": (
            "Run the already frozen suite plan with one execution agent per machine. "
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
    parser.add_argument("--dry-run", action="store_true", help="print the command and prompt without launching Codex")
    args = parser.parse_args()
    if not args.suite_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in args.suite_id):
        parser.error("suite_id must contain only letters, digits, hyphens, and underscores")
    known = {item["id"] for item in load_sources() if item["kind"] == "engine"}
    unknown = set(args.engine) - known
    if unknown:
        parser.error(f"unknown engine IDs: {', '.join(sorted(unknown))}")
    if args.stage == "run" and not (ROOT / "manifests/suites" / args.suite_id).is_dir():
        parser.error(f"suite directory missing: manifests/suites/{args.suite_id}; run prepare first")
    prompt = make_prompt(args.stage, args.suite_id, args.engine)
    command = ["codex", "-C", str(ROOT), prompt]
    if args.dry_run:
        print("Command:", shlex.join(command[:3]), "<generated prompt>")
        print("\nPrompt:\n", prompt, sep="")
        return 0
    executable = shutil.which("codex")
    if executable is None:
        print("Codex CLI is not installed or not on PATH. See https://developers.openai.com/codex/cli/", file=sys.stderr)
        return 1
    os.execv(executable, [executable, *command[1:]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
