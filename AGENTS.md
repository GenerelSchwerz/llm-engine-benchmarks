# LLM engine benchmark workspace

- Read `RUNBOOK.md`, `manifests/sources.json`, the suite's model/workload manifest, and each selected engine guide before running.
- Use `uv run scripts/<name>.py` for this repository's Python entry points. The pinned llama-benchy package is installed from `uv.lock`.
- Keep source, build, runtime environment, model artifacts, commands, result, and revision separate for every engine.
- Research agents report exact per-engine/per-model command packets. The coordinator freezes a plan; one execution agent runs it on each machine.
- Use coherent generation and the pinned llama-benchy track when its chat protocol is supported or adapted. Record an explicit unavailable result otherwise.
- Validate source revisions, actual executable flags, model loading, output coherence, and intended optimization telemetry before measuring throughput.
- Preserve raw commands, prompts, outputs, logs, benchmark JSON, memory samples, errors, and teardown. Mark failed and slower cases.
- Never publish private model artifacts, credentials, personal prompts, or raw captures that contain private data.
