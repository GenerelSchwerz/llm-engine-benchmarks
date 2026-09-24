# Cross-fork MoE benchmarks

This repository documents a reproducible cross-fork MoE benchmark process for the public implementations named in [llama.cpp discussion #24528](https://github.com/ggml-org/llama.cpp/discussions/24528), plus buun's MoE cache fork. It contains guides, manifests, prompts, and installation scripts. Backend source trees, model weights, builds, and benchmark captures are excluded.

## Get started

Requires Python 3.10+ and Git. Clone this repository, then inspect the editable [source list](manifests/sources.json):

```sh
python scripts/install_sources.py
python scripts/install_sources.py --id upstream --id llama-benchy
python scripts/check_sources.py --remote
```

Use `--id NAME` repeatedly to install only the forks you need, or `--all` to install every listed source. The installer checks out the pinned commits under ignored `sources/` and `tools/` directories and verifies existing checkouts without overwriting local changes. Edit `repo`, `branch`, and `sha` in `manifests/sources.json` to add or update a source; update its entry in [the annotated fork inventory](manifests/forks.md) and its guide as well. If a historical commit is no longer fetchable, record it as unavailable rather than replacing it silently.

The installer only downloads source code. Build requirements and model-specific launch candidates are in [the fork guides](guides/); the full agent handoff and measurement rules are in [RUNBOOK.md](RUNBOOK.md). `llama-benchy` also needs installation in an isolated Python environment from its pinned checkout before use.

## Layout

- `manifests/sources.json`: editable machine-readable list of source and tool revisions.
- `manifests/forks.md`: annotated source links, discussion evidence, snapshot commits, and availability.
- `sources/`: shallow source checkouts for public candidates. Treat each checkout as read-only during comparisons.
- `manifests/matrix.md`: model families, controls, and required measurements.
- `guides/`: one fork-specific command guide. Every supported model needs its own launch command and optimization notes.
- `fixtures/`: frozen public prompts for the coherent-text track.
- `results/`: one new directory per immutable run. Never overwrite a result or discard captures.
- `tools/llama-benchy/`: pinned cross-runtime endpoint benchmark tool.
- `scripts/`: pinned source installation and read-only revision checks.

Read [RUNBOOK.md](RUNBOOK.md) before updating sources, benchmarking, or publishing. The current guides are source-reviewed drafts; no live model tests have been run for this new sweep.

## Order of work

1. Pin a commit for each public implementation and record its relationship to upstream. Record unavailable or private variants instead of substituting a different tree.
2. For each fork/model pair, inspect that revision's CLI help and source. Record a command, model artifact, tested quant, and tuning rationale in its guide. Mark unsupported pairs explicitly.
3. Run correctness and fit checks before throughput. Keep source hashes, prompt, token limits, sampling, output, placement, loaded/peak VRAM, system RAM, and final grouped/cache telemetry with each run.
4. Compare matched conditions first. Keep Linux CUDA, Windows WDDM, multi-GPU, UMA, and other runtimes in separate cohorts. Include prefill, TTFT, and sustained decode; note regressions and failed configurations.
5. Publish qualified results to the wiki, then rewrite the repository README around verified claims.

The [existing benchmark evidence](https://github.com/GenerelSchwerz/llama.cpp/wiki/Benchmark-Comparison-Showcase) is historical until each row is rerun against the pinned snapshots in this workspace.

Contributions can follow [CONTRIBUTING.md](CONTRIBUTING.md). The original scripts and documentation here are available under the [MIT license](LICENSE); installed third-party sources keep their own licenses.

## Collection rules

Source collection does not establish that a fork builds, supports a model, or improves speed. No model weights belong in `sources/` or `results/`. Record exact artifacts and hashes in run manifests. Commands in guides are research drafts until their status says they passed the exact binary's `--help` and a live model run.
