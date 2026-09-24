# LLM engine benchmark workspace

- Read `RUNBOOK.md`, `uv run scripts/suite_store.py show SUITE`, the suite matrix, and each selected engine guide. The TUI selects IDs; the preparation agent resolves exact versions and compatibility.
- For a TUI setup request, read `uv run scripts/catalog_cli.py show-request REQUEST_ID`. Save verified discoveries through `catalog_cli.py add-engine` or `add-model` with `--request-id REQUEST_ID`; attach an existing result with `catalog_cli.py attach-result REQUEST_ID RESULT_ID`. Check all exit codes. In the embedded interactive terminal, ask the user directly when blocked and exit when finished; the TUI validates attached results. In monochrome log mode, return JSON matching `manifests/setup-response.schema.json` with `ready` plus every saved result ID, or `needs_input` plus concrete questions. The TUI validates that response and lets the user confirm ready results.
- Write preparation findings through `scripts/suite_store.py record-engine`, `record-model`, and `record-packet`. Run `validate` then `freeze`. Check exit codes and correct rejected records; never claim a suite is frozen after a failed write.
- Use `uv run scripts/<name>.py` for this repository's Python entry points. The pinned llama-benchy package is installed from `uv.lock`.
- Keep source, build, runtime environment, model artifacts, commands, result, and revision separate for every engine.
- Research agents report exact per-engine/per-model command packets. The coordinator freezes a plan; one execution agent runs it on each machine.
- Use coherent generation and the pinned llama-benchy track when its chat protocol is supported or adapted. Record an explicit unavailable result otherwise.
- Validate source revisions, actual executable flags, model loading, output coherence, and intended optimization telemetry before measuring throughput.
- Preserve raw commands, prompts, outputs, logs, benchmark JSON, memory samples, errors, and teardown. Mark failed and slower cases.
- Never publish private model artifacts, credentials, personal prompts, or raw captures that contain private data.
