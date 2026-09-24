# LLM Engine Benchmarks

**Compare LLM inference engines with reproducible runs and inspectable evidence.** Bring a source build, package, container, local binary, or remote service. This project gives you a common process without requiring engines to share a codebase, model format, or hardware backend.

The suite records exact versions, model artifacts, commands, prompts, outputs, timing, and memory use. It checks generated text alongside throughput, so a fast but broken run stays visible.

## Get started

```sh
git clone https://github.com/GenerelSchwerz/llm-engine-benchmarks.git
cd llm-engine-benchmarks
python scripts/install_sources.py                 # list available engines and tools
python scripts/install_sources.py --id ENGINE_ID  # install one pinned Git source
python scripts/check_sources.py --remote          # check local pins and tracking refs
```

Edit [the source list](manifests/sources.json) to add an engine. Git sources install into ignored local directories; package, container, remote, and local entries provide installation notes instead. See the [source format](manifests/source-schema.md) for examples.

Then choose models and workloads in [the suite matrix](manifests/matrix.md), prepare an [engine guide](guides/TEMPLATE.md), and follow [the runbook](RUNBOOK.md). The runbook covers a coherent-text track and a separate [llama-benchy](https://github.com/eugr/llama-benchy) track. Engines without a compatible chat endpoint need an adapter for the latter.

## Explore

| Looking for… | Start here |
| --- | --- |
| The full benchmark process and agent handoff | [Runbook](RUNBOOK.md) |
| Editable engines and tools | [Source list](manifests/sources.json) · [source format](manifests/source-schema.md) |
| Existing setup examples | [Engine catalog](manifests/engines.md) · [guides](guides/) |
| Prompts and result fields | [Fixtures](fixtures/README.md) · [result template](manifests/run-template.json) |
| Adding an engine or submitting results | [Contributing](CONTRIBUTING.md) |

The included llama.cpp, FreeToken, and KTransformers guides are **research starting points**, not verified performance results. Engine code, model weights, builds, and raw captures are not shipped here.

For automated work, [AGENTS.md](AGENTS.md) gives agents the workspace rules; the runbook contains the procedure shared by humans and agents. Original project files are [MIT licensed](LICENSE). Third-party engines keep their own licenses.
