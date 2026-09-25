# TheTom TurboQuant MoE-cache fork

Research draft, 2026-09-24. Reviewed [`feature/turboquant-kv-cache` at `a3d5603d110b`](https://github.com/TheTom/llama-cpp-turboquant/tree/a3d5603d110bda29222d2011596cdc84d7fa532d), [`common/arg.cpp`](https://github.com/TheTom/llama-cpp-turboquant/blob/a3d5603d110bda29222d2011596cdc84d7fa532d/common/arg.cpp), [MoE cache design and tuning guide](https://github.com/TheTom/llama-cpp-turboquant/blob/a3d5603d110bda29222d2011596cdc84d7fa532d/docs/backend/MOE-CACHE.md), and [TurboQuant KV guide](https://github.com/TheTom/llama-cpp-turboquant/blob/a3d5603d110bda29222d2011596cdc84d7fa532d/docs/KV-cache-quantization.md). The fork has CUDA/HIP, Metal, and Vulkan cache providers according to its source guide; benchmark each provider separately. No live build or model run has validated these commands.

## Placement and model-specific launch

`--moe-cache auto` is the documented default and can keep stock placement when the model fits. `--fit on --moe-cache auto` is the recommended cache-aware placement; the cache only engages if routed experts are assigned to host memory, an eligible GPU and sufficient spare VRAM exist, and an actual pool is allocated. A server saying `MoE cache disabled (...)` or lacking `[moe-cache] enabled` is not a cache result. `--moe-cache on` forces canonical CPU expert weights and disables weight repacking; a positive integer caps MiB **per device**; `soft` first tries stock placement. These modes have different weight placement and repacking, so compare them as separate configurations. The default automatic reserve is 3072 MiB and automatic slabs require at least 1 GiB after reserve. For constrained VRAM, investigate `GGML_CUDA_MOE_CACHE_RESERVE_MB`, then verify pool slots and OOM behavior. [Parser](https://github.com/TheTom/llama-cpp-turboquant/blob/a3d5603d110bda29222d2011596cdc84d7fa532d/common/arg.cpp), [cache guide](https://github.com/TheTom/llama-cpp-turboquant/blob/a3d5603d110bda29222d2011596cdc84d7fa532d/docs/backend/MOE-CACHE.md).

| Model | Source support | Initial server recipe | Follow-up optimization |
| --- | --- | --- | --- |
| Qwen3.6-35B-A3B | `qwen35` family and fork cache measurements | Below | If fully resident, cache is expected dormant; measure stock fit and forced CPU-expert mode separately. |
| Qwen3.8-Flash-Next | `qwen4exp` architecture present; actual GGUF untested | Below | Target-only first; MTP/secondary scheduler needs its own arm and counters. Quantized KV quality must be checked. |
| DeepSeek V4 Flash | `deepseek4` architecture and fork cache measurements | Below | Target-only first; test DSpark separately, keep draft memory and throughput separate. |

Set `Q36`, `Q38`, and `DSV4` to exact GGUF paths. Set `CTX`, `THREADS`, `PORT`. These start with `--fit on --moe-cache auto` and q8_0 KV to avoid confounding the cache comparison with a new KV codec. Ensure `CTX` and `-ngl` fit; **do not add an explicit `-ngl` to the autofit arm** without recording that override. If the cache stays dormant because the model fits entirely in VRAM, that is a valid fit result, not a cache-on result.

Qwen3.6:

```sh
./build/bin/llama-server -m "$Q36" -a q36 -c "$CTX" \
  --fit on --moe-cache auto --jinja -fa on -ctk q8_0 -ctv q8_0 \
  -t "$THREADS" --port "$PORT" -lv 4
```

Qwen3.8 Flash Next:

```sh
./build/bin/llama-server -m "$Q38" -a q38 -c "$CTX" \
  --fit on --moe-cache auto --jinja -fa on -ctk q8_0 -ctv q8_0 \
  -t "$THREADS" --port "$PORT" -lv 4
```

DeepSeek V4 Flash:

```sh
./build/bin/llama-server -m "$DSV4" -a dsv4 -c "$CTX" \
  --fit on --moe-cache auto --jinja -fa on -ctk q8_0 -ctv q8_0 \
  -t "$THREADS" --port "$PORT" -lv 4
```

For a controlled host-expert comparison after autofit, use `--cpu-moe -ngl N --moe-cache off` and the same placement with `--moe-cache on` or a fixed MiB budget. Verify actual repacking and placement in logs; the fork guide notes that `on` versus `off` can change repacking even at matched flags. `--repack off` can reduce that confound, at a possible cost to absolute speed. The cache is decode-oriented: prompt batches above its token limit bypass it. Warm with varied decode and preserve final hit/miss, fusion, fallback, and per-device pool counters. `auto` can reject small experts or low capacity, particularly on smaller GPUs. [Cache method and limitations](https://github.com/TheTom/llama-cpp-turboquant/blob/a3d5603d110bda29222d2011596cdc84d7fa532d/docs/backend/MOE-CACHE.md).

TurboQuant KV is a **separate** sweep: `-ctk q8_0 -ctv turbo3` is documented, but alters KV memory and possibly quality. Do not attribute its gains to the expert cache. The [KV guide](https://github.com/TheTom/llama-cpp-turboquant/blob/a3d5603d110bda29222d2011596cdc84d7fa532d/docs/KV-cache-quantization.md) says MLA models lack a separate V cache, and recommends quality validation for low-bit KV. Record K and V types for every model; test the exact GGUF architecture before assuming a codec applies.

## Two measurements per model

**Coherent text:** Start one of the three servers in a fresh process and replace the alias in the request with `q36`, `q38`, or `dsv4`. Save visible and reasoning text, finish reason, generated count, and server log. Apply the runbook's minimal output sanity gate before benchmarking throughput; report answer completion separately.

```sh
curl -fsS "http://127.0.0.1:$PORT/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"q36","messages":[{"role":"user","content":"Write a short Python function to merge sorted lists, then explain its complexity."}],"temperature":0,"max_tokens":512}'
```

**`llama-benchy`:** Select the exact tokenizer and served alias for each model: `Q36_TOKENIZER/q36`, `Q38_TOKENIZER/q38`, `DSV4_TOKENIZER/dsv4`. The [benchy CLI](https://github.com/eugr/llama-benchy#usage) is documented for OpenAI-compatible `/v1/chat/completions`; validate the installed `--help` and endpoint response. Its coherence test is enabled by default.

```sh
uv run --project tools/llama-benchy llama-benchy \
  --base-url "http://127.0.0.1:$PORT/v1" \
  --model "$TOKENIZER" --served-model-name "$ALIAS" \
  --pp 2048 --tg 512 --depth 0 8192 --runs 3 --warmup-runs 2 \
  --latency-mode generation --concurrency 1 --format json \
  --save-result "$RESULT_JSON"
```

Use the same prompt corpus, output length, context, quant, GPU set, and KV types across engines. Record actual peak VRAM and RAM, placement, cache engagement, TTFT, prefill, decode, and output coherence. Keep target-only, MTP, and KV-codec results in distinct rows. No performance result is claimed from these source-reviewed templates.
