# Benchmark matrix

## Initial model families

| Model family | Why it is included | Artifact status |
| --- | --- | --- |
| Qwen3.6 35B A3B | Shared MoE baseline across several forks and FreeToken | Pin one GGUF and native checkpoint separately; do not assume weight equivalence |
| Qwen3.8 Flash Next | Large MoE, PLE, MTP, and host-memory pressure | Pin GGUF quant and optional MTP sidecar separately |
| DeepSeek V4 Flash | Large CPU-resident expert workload and multi-GPU comparison | Pin GGUF quant and DSpark availability per fork |
| Gemma 4 26B A4B | Prior strong cache result | Artifact to pin |
| Nemotron 3.5 Lightning 30B A3B | Different MoE expert layout | Artifact to pin |
| GPT-OSS 20B | Prior cache regression control | Artifact to pin |
| LFM2.5 8B A1B | Prior cache regression and grouped-certificate failure | Artifact to pin |
| Ornith 1.5 35B A3B | Prior grouped path and fan-out result | Artifact to pin |

The first three families drive command-guide research because they are directly discussed in #24528. The remaining families refresh the older public sweep. A family enters a comparison only after a single exact model artifact and its provenance are selected for every compatible runtime.

## Required legs for each supported fork/model pair

1. Baseline placement or cache disabled, as the implementation defines it.
2. Cache enabled with recorded capacity and actual cache/grouped-path counters.
3. MTP or other drafting as a separate leg where both model and runtime support it.
4. At least short-prompt single-request and long-prompt single-request runs; parallel requests where supported.

Record the fork commit, executable and shared-library hashes, model and draft hashes, hardware and driver, full command and environment, prompt hash, request JSON, output and stop reason, prefill, TTFT, decode, wall time, RAM, loaded and peak VRAM, errors, and teardown. Use matched VRAM and workload before quoting speed ratios. One coherent completion is a prerequisite, not a quality study.

Do not silently replace a missing leg with another fork, quant, model revision, or hardware cohort. Mark it `unsupported`, `unavailable`, `failed`, or `not yet run` with a reason.
