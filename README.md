# LLM engine benchmarks

A reusable workflow for comparing **any LLM inference engines** under recorded workloads and hardware. An engine can be a source build, installed package, container, remote service, or local executable. The included llama.cpp variants, FreeToken, and KTransformers are examples for an MoE study; the workflow does not depend on their architecture or ancestry.

This repository contains manifests, engine guides, prompts, and run instructions. It does not include engine code, model weights, builds, or captured benchmark results.

## Start a suite

1. Edit [sources.json](manifests/sources.json) to list the engines and tools you want. The [source schema](manifests/source-schema.md) covers Git, package, container, remote, and local entries. Add an engine-specific guide based on [the template](guides/TEMPLATE.md).
2. For Git sources, run `python scripts/install_sources.py --id ENGINE_ID` or `--all`. The script installs pinned checkouts into ignored `sources/` and `tools/` directories. For package, container, remote, and local engines, follow the entry's `install_notes` and record the resolved version or digest in the suite manifest.
3. Run `python scripts/check_sources.py --remote` to inspect Git pins and tracking refs. Treat package, container, remote, and local revisions as requiring engine-specific verification.
4. Define model artifacts, workload fixtures, comparison cohorts, and output checks in [matrix.md](manifests/matrix.md). Follow [RUNBOOK.md](RUNBOOK.md) for agent handoff, execution, collection, and publication.

List available installations without downloading anything:

```sh
python scripts/install_sources.py
```

The included [engine catalog](manifests/engines.md) and [guides](guides/) are source-reviewed examples. Their commands require binary and model validation before they can support a performance claim. The two benchmark methods are coherent generation and [llama-benchy](https://github.com/eugr/llama-benchy); an engine without a compatible chat endpoint needs an adapter or an explicit unavailable result for the latter.

See [CONTRIBUTING.md](CONTRIBUTING.md) to add an engine or workload. Original scripts and documentation use the [MIT license](LICENSE); installed engines retain their own licenses.
