# Cross-fork benchmark runbook

This is the top-level guide for collecting fork updates, preparing model-specific commands, running the two benchmark methods, and publishing verified results. Read [the source inventory](manifests/forks.md), [model matrix](manifests/matrix.md), [tooling snapshot](manifests/tooling.md), and the relevant file in `guides/` before acting. At the 2026-09-24 collection snapshot, this workspace has only source and guide preparation; live model runs await a later user instruction.

## Roles and handoff

One coordinating agent owns the suite revision and publication. Fork research fans out to subagents, with one fork per research assignment where practical. Research agents inspect source and documentation; they do not build or use the benchmark GPU. The coordinator coalesces their command packets into one frozen run plan. **Exactly one execution agent** then builds, runs, records, and evaluates all arms serially on a given machine. Do not let several agents launch servers or tune against the same GPU concurrently.

### Fan-out after an update check

1. The coordinator records the last published suite revision, its fork SHAs, model/draft hashes, guide revisions, benchy commit, prompt hashes, and hardware cohort. Preserve the old manifest and results.
2. Create `manifests/suites/<suite-id>/`, then run `python scripts/check_sources.py --remote > manifests/suites/<suite-id>/source-check.json` to check pinned local heads and tracking branches without moving them. A branch disappearing is an `unavailable` result, never a reason to silently switch branches.
3. Assign each fork to a research agent. The assignment contains its exact old SHA, observed remote SHA, models in scope, previous guide, and hardware cohort.
4. If the source SHA, model artifact, benchmark tool, and relevant hardware cohort are unchanged since the last **validated** run, the agent may report the previously validated args as `reuse`. It still checks the guide and reports the exact source of those args. **Only this unchanged case permits an unqualified "previously validated" claim.**
5. If any of those inputs changed, the agent reports `review required`. It examines the commit diff, build files, CLI parser/help text in source, model support, cache/placement logic, and changed defaults. It updates its fork guide and proposes model-specific commands with code references. Those commands remain research drafts until the execution agent builds the pinned revision, captures its actual `--help`, and completes a model run.
6. Every research agent returns one [command packet](manifests/command-packet-template.md) per fork/model/benchmark mode, including unsupported and failed-to-resolve pairs. Avoid one generic command for all models.

### Coalescing gate

The coordinator checks that every candidate has an exact revision, model artifact, benchmark mode, per-model command, tuning rationale, and support status. It rejects a packet if flags are from another fork, the command uses a moving ref, a quant or checkpoint differs without an explicit comparison tier, or the memory target is not stated. Resolve conflicts in the fork guide before scheduling. Freeze the accepted packets and model hashes in a dated `manifests/suites/<suite-id>/` directory. An update after this point starts a *new* suite revision.

The execution agent receives only that frozen plan. It may reject an invalid command and request a revised packet; it does not improvise performance flags during a measured run. It owns build isolation, single-GPU/process locking (including the existing `/tmp/beellama-single-gpu.lock` on this host), warmup, request execution, raw collection, teardown, and the final result ledger.

## Fork-specific guide contract

Every public runnable fork needs its own guide. The guide records a pinned branch and SHA, build/backend requirements, executable and library paths, model support, source-backed flags, known failure modes, a baseline and tuned server command **for each supported model**, and both benchmark methods. Explain why each optimization is chosen for that fork and model. Include cache size/placement, batching, KV type, host loading and pinning, speculative/draft settings, parallelism, and relevant environment variables. Mark unsupported models explicitly. Guides are research drafts until the runner records build, `--help`, and coherent output at that exact SHA.

For an unchanged fork, reuse the last validated command only if its exact model, quant, machine cohort, workload, and tool revision also match. A different model or quant requires a separate command packet even when the fork SHA matches.

## Build and model gates for a future live sweep

1. Save the current machine state and ensure no benchmark server, profiler, or other GPU workload is active. Use a machine-specific lock so only one execution agent can operate it.
2. Build each fork from its pinned source into its own `builds/<fork-id>/<sha>/` path. Record compiler, CUDA/driver, CMake options, build log, executable hash, and loaded shared-library hashes. Never mix libraries from sibling forks or reuse a build directory across SHAs.
3. Capture that binary's `--help` and compare the guide's flags to it. A flag rejection or changed semantic returns the packet to research; it does not trigger an on-the-fly substitution.
4. Pin model and draft artifacts with source URL/revision and SHA256. Check complete shard sets and tokenizer/chat template. Native checkpoints and converted GGUFs are distinct artifacts unless exact lineage and weight equivalence are established.
5. For each fork/model, test startup, fit, coherent completion, and actual cache/grouped/draft-path telemetry before measuring speed. Record failures as outcomes. An allocation or offload count alone does not prove that the intended cache path ran.
6. Tune in a separate calibration stage under a declared memory ceiling. Vary only documented knobs, record all trials including regressions, then freeze the winning *full command* before measured repeats. Retain stock-placement and cache-off controls where applicable. Do not assume the same cache count or `-ub` is optimal across forks or models.

## Method A: coherent-text workload

Use frozen, nonprivate tasks from `fixtures/`. At minimum include a coding task and a systems explanation task; add a long-context task when the model and hardware support it. The response must complete the task coherently. Preserve exact request JSON, streamed response chunks, final text, any reasoning field, output-token accounting, stop reason, prompt hash, and a short human-readable quality verdict with concrete defects. A truncated, repetitive, empty, or erroring response remains in the results but cannot support a headline performance claim.

Use the same prompt, token ceiling, sampling, concurrency, and context geometry within a comparison. Do not force the same *server flags* across forks; each guide supplies its optimized command. Report TTFT, server prefill, client-perceived decode, sustained delivery, wall time, RAM, loaded/peak VRAM, cache/draft acceptance, and errors. Keep MTP and no-MTP arms separate. Numerical output differences caused by expert placement should be characterized with matched-placement controls rather than treated as automatic corruption or automatic correctness.

## Method B: pinned `llama-benchy`

Use the checkout pinned in [tooling.md](manifests/tooling.md). It targets OpenAI-compatible `/v1/chat/completions`, so verify the exact endpoint and served model alias for each fork. Keep its own built-in coherence probe enabled, but still run Method A independently. Freeze its corpus and tokenizer revisions; record their hashes and the tool commit. Its reported prompt speed estimates and post-first-content-token decode definition are distinct from Method A's server timers.

Before a measured run, verify the requested tokenizer actually loaded. This pinned tool silently falls back to GPT-2 if both tokenizer loaders fail; reject the arm if its log reports that fallback. Hash the cached book text as well as recording its URL, since the tool reuses a local cache file on later runs.

The default measurement grid is `--pp 2048 --tg 512 --depth 0 32768 --runs 3 --warmup-runs 1 --latency-mode generation --format json`. Run concurrency 1 and 4 as separate server configurations, with enough server slots/context for each. Add a deeper context case only when `depth + pp + tg` fits the configured context and the model is known to support it. Example client command after installing the pinned checkout in its isolated environment:

```sh
tools/llama-benchy/.venv/bin/llama-benchy \
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

`MODEL_ID` identifies the model to benchy, while `SERVED_MODEL_ID` is the exact name accepted by the server. Both, the tokenizer, concurrency, and server launch come from the fork/model command packet. Confirm actual generation length; `--tg` is a request, not proof of exact output count. Use `--exact-tg` only when the runtime is verified to honor the fields it sends. Keep prefix-caching experiments in their own arm. Treat a blank decode rate for a one-chunk streaming response as unavailable, not zero; the [llama-benchy documentation](https://github.com/eugr/llama-benchy) defines that behavior.

## Results and comparison rules

Create one immutable directory per fork/model/mode/configuration/repetition. Start its metadata from [the run manifest template](manifests/run-template.json). Preserve command vectors, environment variable *names and nonsecret values*, Git SHAs, model hashes, process tree, logs, request/response, benchy JSON, GPU/RAM samples, stop reason, errors, and teardown proof. Keep captures private if prompts or logs contain personal data or credentials.

Compare within the same hardware/OS cohort and under a stated memory envelope. Report prefill and decode separately, plus TTFT and completion wall time. Show median and spread for repeats; retain individual results. Put unmatched VRAM, different checkpoint lineage, failed output, and unsupported modes in clearly labeled rows. A faster row with worse output or missing cache-path evidence does not become a headline win. Do not collapse coherent-text and llama-benchy scores into one ratio.

## Wiki publication after an explicit request

The execution agent produces a proposed result table and links to the retained raw local artifacts. The coordinator checks its arithmetic and qualifications, fetches the current wiki (local checkout: `/home/gencoolpc/llama.cpp.wiki`, remote: `https://github.com/GenerelSchwerz/llama.cpp.wiki.git`), and edits only affected benchmark/model/setup pages plus `Home.md`. Check `git status`, fetch, and fast-forward before editing; preserve user edits and dated historical tables. Likely pages include `Benchmark-Comparison-Showcase.md`, model reports, `Owner-Verified-Benchmark-Evidence.md`, `Benchmark-Future-Coverage.md`, and `Notable-Runs.md`. State exact commits, artifact hashes, hardware, method, memory match, negative cases, and limits. Commit and push the wiki only when the user has asked to publish that sweep; re-fetch GitHub pages to verify the rendered data and links. Rebuild the repository README after the wiki's current claims are settled.

## One-sentence future assignment

"Read `/home/gencoolpc/cross-fork-benchmarks/RUNBOOK.md`; fan out source/arg review for every public fork, coalesce frozen model-specific command packets, use one execution agent to rerun both coherent-text and llama-benchy tracks, verify and retain results, then publish the qualified sweep to the GitHub wiki."
