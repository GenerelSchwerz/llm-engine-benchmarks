# Cross-fork MoE benchmarks

This workspace collects the public implementations named in [llama.cpp discussion #24528](https://github.com/ggml-org/llama.cpp/discussions/24528), plus buun's MoE cache fork. It is separate from the existing `moe-cache-tests` execution console and its preserved results.

## Layout

- `manifests/forks.md`: source links, discussion evidence, snapshot commits, and availability.
- `sources/`: shallow source checkouts for public candidates. Treat each checkout as read-only during comparisons.
- `manifests/matrix.md`: model families, controls, and required measurements.
- `guides/`: one fork-specific command guide. Every supported model needs its own launch command and optimization notes.
- `fixtures/`: frozen public prompts for the coherent-text track.
- `results/`: one new directory per immutable run. Never overwrite a result or discard captures.
- `tools/llama-benchy/`: pinned cross-runtime endpoint benchmark tool.
- `scripts/`: validation and report tools added only after the command contract is frozen.

Read [RUNBOOK.md](RUNBOOK.md) before updating sources, benchmarking, or publishing. As of this collection phase, only source and documentation research has been done; no live model tests have been run here.

## Order of work

1. Pin a commit for each public implementation and record its relationship to upstream. Record unavailable or private variants instead of substituting a different tree.
2. For each fork/model pair, inspect that revision's CLI help and source. Record a command, model artifact, tested quant, and tuning rationale in its guide. Mark unsupported pairs explicitly.
3. Run correctness and fit checks before throughput. Keep source hashes, prompt, token limits, sampling, output, placement, loaded/peak VRAM, system RAM, and final grouped/cache telemetry with each run.
4. Compare matched conditions first. Keep Linux CUDA, Windows WDDM, multi-GPU, UMA, and other runtimes in separate cohorts. Include prefill, TTFT, and sustained decode; note regressions and failed configurations.
5. Publish qualified results to the wiki, then rewrite the repository README around verified claims.

The [existing benchmark evidence](https://github.com/GenerelSchwerz/llama.cpp/wiki/Benchmark-Comparison-Showcase) is historical until each row is rerun against the pinned snapshots in this workspace.

## Collection rules

Source collection does not establish that a fork builds, supports a model, or improves speed. No model weights belong in `sources/` or `results/`. Record exact artifacts and hashes in run manifests. Commands in guides are research drafts until their status says they passed the exact binary's `--help` and a live model run.
