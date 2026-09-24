# Suite model and workload matrix

A suite can target **any** model family and engine. Define the exact model artifact, revision/hash, tokenizer, context length, quantization or dtype, prompt fixtures, sampling, output ceiling, concurrency, hardware cohort, and memory ceiling before running. Native checkpoints and converted artifacts are separate comparison tiers unless their lineage and weight equivalence are established. Mark unsupported engine/model pairs explicitly.

## Example MoE study

The following candidates are examples, not required models:

| Model family | Study interest | Artifact status |
| --- | --- | --- |
| Qwen3.6 35B A3B | Shared MoE comparison | Pin GGUF and native checkpoint separately |
| Qwen3.8 Flash Next | Large MoE and draft behavior | Pin exact quant and optional draft sidecar |
| DeepSeek V4 Flash | CPU-resident experts and multi-GPU | Pin artifact and draft availability per engine |
| Gemma 4 26B A4B, Nemotron 3.5 Lightning 30B A3B, GPT-OSS 20B, LFM2.5 8B A1B, Ornith 1.5 35B A3B | Broader regression coverage | Pin artifacts before admission |

For a dense-model study, replace these rows entirely. The same runbook applies without cache or draft-specific legs.

## Required comparison dimensions

1. A baseline configuration and any optimized configuration, with the engine's actual effective placement and settings recorded.
2. Coherent generation on frozen prompts and a separate llama-benchy track where the protocol is supported or adapted.
3. Short and sustained generation, plus concurrency where the engine supports it.
4. An explicit status for every planned pair: `complete`, `failed`, `unsupported`, `unavailable`, or `not yet run`.

Record engine version, executable or image digest, model/draft hashes, hardware, full command and environment, prompt hash, request/response, prefill, TTFT, decode, wall time, memory, errors, and teardown. Optimization-specific counters such as cache hits or draft acceptance are required only when that optimization is claimed.
