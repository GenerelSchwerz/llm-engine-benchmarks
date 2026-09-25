# LLM engine benchmark runbook

Use this guide for a reproducible comparison of any LLM inference engines. Start with the editable [source list](manifests/sources.json), local [model setups](manifests/models.md), [engine catalog](manifests/engines.md), [suite matrix](manifests/matrix.md), [tool pin](manifests/tooling.md), and the selected engine guides. The included MoE guides are research examples; no new live sweep is implied by them. Humans can use `uv run scripts/tui.py` to add simple locators and launch the Codex preparation or run stage.

Preparation creates a draft in the local SQLite catalog. The agent reads it with `uv run scripts/suite_store.py show SUITE`, then writes exact engine revisions with `record-engine` (and `--installed-path PATH` for a new Git checkout), model revisions and tokenizer with `record-model`, and each engine/model/method command packet with `record-packet`. The CLI hashes local artifacts and verifies Git checkout HEAD against the recorded commit. It rejects missing or invalid data; the agent must fix errors and run `validate` and `freeze`. After the handoff is complete, run `finish-prepare SUITE --message 'Verified summary'`. The TUI reports this completion separately from the frozen plan because an interactive Codex terminal stays open between turns. This is the end of preparation; model loading, coherent output, and measurements belong to `run`. `run` refuses an unfrozen suite. The catalog stores a snapshot of the selected setups, so later TUI edits do not change an existing suite.

## Fan-out, coalescing, and one runner

A coordinator owns the suite revision and result publication. Research agents each review one engine and return [command packets](manifests/command-packet-template.md) for every assigned model and method. They do not consume the benchmark machine. The coordinator coalesces the packets into a frozen plan. **One execution agent per machine** handles installation, builds, runs, raw collection, and teardown serially under a machine-specific lock.

1. Record the prior validated suite's engine versions, model/draft hashes, guide revisions, benchmark-tool version, prompt hashes, protocol-adapter versions, and hardware cohort.
2. Create `manifests/suites/<suite-id>/`. With the default `--no-check-updates` mode, run `uv run scripts/check_sources.py --id <selected-id> > manifests/suites/<suite-id>/source-check.json` for selected Git entries (repeat `--id`); this verifies local pins without querying upstream. With `--check-updates`, add `--remote` and review changed refs. For package, container, remote, and local entries, capture their installed version/digest with the guide's verification command. Source checks are read-only. Record the update-check mode in the suite plan.
3. Fan out engine assignments with the old validated revision, observed current revision, models, previous guide, and hardware cohort.
4. An agent may report `reuse` and the previously validated arguments **only if** engine revision, model artifact, tool, adapter, and hardware/workload cohort remain unchanged. It cites the exact prior command and result. Without an upstream check, label remote freshness `not checked`; do not imply the tracking branch is unchanged. An unchanged local source alone is insufficient.
5. If any input changes, report `review required`. Reinspect the relevant source or vendor documentation, build/install requirements, CLI/API schema, defaults, model support, and optimization behavior. Propose model-specific commands with references. A proposal remains a draft until the runner verifies the installed engine and completes a model run.
6. The coordinator rejects packets missing an exact version, model artifact, method, full command/request, support status, memory target, or tuning rationale. It resolves conflicts in the guide and freezes accepted packets and artifact hashes. A later update creates a new suite revision.

The runner may return an invalid packet for revision; it does not improvise performance options during measurement.

## Engine guide contract

Each selected engine needs an install/verify guide, exact version, model support table, baseline and tuned commands **per model**, launch/health/stop steps, endpoint or CLI behavior, and both measurement methods. Include runtime environment, GPU/CPU placement, batching, parallelism, KV/cache/draft settings only where relevant. Explain each optimization using source or vendor documentation. Mark unsupported pairs. An engine without a faithful OpenAI-compatible chat endpoint needs a documented adapter for llama-benchy; otherwise record that method as `unavailable` rather than reporting a substituted metric.

Git clones are installed from `manifests/sources.json` with `uv run scripts/install_sources.py`; the manifest also supports non-Git entries with explicit installation notes. Never update a source checkout in the middle of a suite.

## Build, model, and calibration gates

1. Save machine state, choose a lock, and ensure no competing workload uses the target resources. Keep each engine's build, libraries, container, or virtual environment separate. Record compiler/driver/backend and executable or image digest.
2. Check the actual binary `--help`, API schema, or service version against the guide. Return rejected or changed options to research.
3. Pin model and draft artifacts with URL/revision and SHA256 where files are available. Record tokenizer, chat template, quant/dtype, complete shards, and provenance. Keep native checkpoints and converted GGUFs in separate comparison tiers unless equivalence is established.
4. Verify startup, health, memory fit, coherent completion, and any claimed optimization path before timing. An allocation or offload count alone is not proof that a cache or draft path executed.
5. Tune in a separate calibration stage under a declared memory ceiling. Record every trial, including regressions. Freeze the winning full command and a suitable baseline before measured repeats.

## Method A: coherent generation

Use frozen, nonprivate tasks from `fixtures/` or add suite-specific fixtures with hashes. Include at least a coding task and a technical explanation; use a long-context task when supported. Preserve exact request/invocation, streaming chunks when available, final text, token accounting, stop reason, prompt hash, and a short quality verdict with concrete defects. Incoherent, empty, truncated, or erroring output remains a result but cannot support a headline speed claim.

Match prompt, token ceiling, sampling, concurrency, context geometry, and hardware/memory cohort across comparisons. Engines may need different launch flags. Report TTFT, prefill, client-perceived decode, wall time, RAM, VRAM, and errors. Record cache/draft counters only for claims about those features. If engine outputs differ materially, treat speed differences as observational until quality is evaluated.

## Method B: pinned llama-benchy

Use the `llama-benchy` package pinned in `pyproject.toml` and `uv.lock`, as described in [tooling.md](manifests/tooling.md). Install it with `uv sync`. It sends OpenAI-compatible `/v1/chat/completions` requests. Verify the engine's endpoint and exact served model alias, or pin a protocol adapter and document its semantics and overhead. Keep the tool's coherence probe enabled, but still run Method A independently.

Freeze corpus bytes and tokenizer revision; record their hashes and the tool commit. At the pinned revision, a failed tokenizer load falls back to GPT-2. Reject the arm if its log reports that fallback. Hash the cached book text as well as recording its URL.

The default grid is `--pp 2048 --tg 512 --depth 0 32768 --runs 3 --warmup-runs 1 --latency-mode generation --format json`, subject to model context support. Run concurrency 1 and 4 as separate configurations with sufficient server capacity. Example using the locked project environment:

```sh
uv run llama-benchy \
  --base-url "http://127.0.0.1:${PORT}/v1" \
  --model "$MODEL_ID" --served-model-name "$SERVED_MODEL_ID" \
  --tokenizer "$TOKENIZER_ID" \
  --pp 2048 --tg 512 --depth 0 32768 \
  --runs 3 --warmup-runs 1 --latency-mode generation \
  --concurrency "$CONCURRENCY" --format json \
  --save-result "$RUN_DIR/benchy.json" \
  --emit-progress "$RUN_DIR/benchy-progress.jsonl" \
  --exit-on-first-fail
```

Set the identifiers and server launch from the engine/model packet. Confirm actual output length; `--tg` is a request, not proof of exact generation. Use `--exact-tg` only after verifying the engine honors the fields it sends. Treat a blank decode rate for a one-chunk response as unavailable. Do not combine coherent-generation and benchy rates into one score.

## Results and comparison

Create an immutable result directory per engine/model/method/configuration/repetition. Start from [run-template.json](manifests/run-template.json). Keep full command vectors, nonsecret environment settings, engine/tool versions, model hashes, logs, request/response, benchy JSON, resource samples, stop reason, errors, and teardown proof. Store private captures outside public Git.

Compare within a hardware/OS cohort and stated memory envelope. Report prefill, decode, TTFT, and completion wall time separately, with median and spread across repeats. Retain individual results. Label unmatched artifacts, quantization, model lineage, failed output, unsupported modes, and adapter overhead. A faster row with worse output or missing optimization evidence is not a headline win.

## Publication

The runner proposes a qualified table with raw artifact references. The coordinator checks arithmetic and limitations, then updates the designated report or wiki only when publication is requested. Fetch current content first, preserve existing edits and dated tables, state exact versions/hashes/hardware/methods, and verify the published rendering and links.

## Reusable agent assignment

"Read `RUNBOOK.md`; fan out engine/version and model-argument review, coalesce frozen model-specific command packets, use one execution agent per machine for coherent-generation and llama-benchy tracks, retain and evaluate raw results, then publish the qualified suite to the designated destination."
