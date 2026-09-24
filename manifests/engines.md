# Example engine catalog

The editable installation list is [sources.json](sources.json). This catalog explains why the initial entries are included; it is not an eligibility list. Add any LLM inference engine with a reproducible version and an engine-specific setup guide. Entries need not share code, model format, quantization, hardware backend, or API.

| Engine or family | Example IDs | Benchmark role |
| --- | --- | --- |
| llama.cpp and derivatives | `upstream`, `generelschwerz`, `leloch-v1`, `leloch-v2`, `lidenburg`, `thecodacus`, `thetom`, `giveen-current`, `miltos22`, `atomic-germ`, `mclaudod`, `buun`, `csantiago78`, `danielhanchen-mtp` | GGUF runtimes, optimization variants, and target-only or draft controls; some entries are dependencies rather than independent competitors |
| FreeToken | `freetoken` | Independent native-checkpoint runtime with CPU/GPU/hybrid strategies |
| KTransformers | `ktransformers` | Independent heterogeneous runtime |
| Guanaco | `guanaco` | Companion project requiring its own deployment and model contract |
| llama-benchy | Installed by `uv sync --locked` | Benchmark client, pinned in `pyproject.toml` and `uv.lock` rather than the engine list |

A candidate enters a comparison only after its exact version, model artifact, tokenizer, hardware cohort, workload, and output checks are recorded. A dependency or companion project is not automatically a runnable comparison arm. Source inclusion alone proves no build, model support, or speed claim.
