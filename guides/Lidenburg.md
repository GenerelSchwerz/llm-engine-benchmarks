# Lidenburg three-tier expert cache

Research draft, 2026-09-24. Reviewed [`moe-expert-caching` at `e85e4d90cd44`](https://github.com/Lidenburg/llama.cpp/tree/e85e4d90cd44a8c8332093b0c97a53fa13137f5e), its [fork README](https://github.com/Lidenburg/llama.cpp/blob/e85e4d90cd44a8c8332093b0c97a53fa13137f5e/README.md), [argument parser](https://github.com/Lidenburg/llama.cpp/blob/e85e4d90cd44a8c8332093b0c97a53fa13137f5e/common/arg.cpp), and [three-tier implementation](https://github.com/Lidenburg/llama.cpp/blob/e85e4d90cd44a8c8332093b0c97a53fa13137f5e/ggml/src/ggml-backend.cpp). Commands below require `llama-server --help` and model-loading validation on the built revision before benchmark use.

## Scope and tuning

This proof-of-concept keeps hot experts in VRAM, warm experts in pinned RAM, and reads misses from GGUF through Linux `io_uring`/`O_DIRECT`. It is Linux-only, single-GPU tested, optimized for generation throughput, and explicitly **not tested with MTP or concurrent requests**. Do not run its cache arms as MTP or parallel-request comparisons until correctness is demonstrated. The README says `GGML_OP_OFFLOAD_MIN_BATCH=1` is mandatory and `--mmap` is required for the disk tier. It gives `GGML_EXPERT_CACHE_MAX` (GPU experts per tensor) and `GGML_EXPERT_RAM_CACHE_MAX` (pinned-RAM experts per tensor) as tunable capacity knobs. Start with README's Qwen3.6 setting `90/166`, then sweep GPU slots against available VRAM and RAM slots against available pinned host memory. Cache misses can become storage-bound; retain disk throughput and read-wait telemetry. Its next-layer prefetch is compiled off by default, so do not attribute results to predictive prefetch. [Source and measured configurations](https://github.com/Lidenburg/llama.cpp/blob/e85e4d90cd44a8c8332093b0c97a53fa13137f5e/README.md).

| Model | Status at reviewed revision | Server recipe |
| --- | --- | --- |
| Qwen3.6-35B-A3B | Demonstrated in fork README | Below |
| Qwen3.8-Flash-Next | **Unsupported**: no `qwen4exp` model architecture | None; obtain an updated port before testing |
| DeepSeek V4 Flash | **Unsupported**: no `deepseek4` model architecture | None; obtain an updated port before testing |

Set `Q36` to the exact GGUF, `PORT` to a free port, and choose `CTX` and `THREADS` per host. The first command is a draft of the README's server configuration. It forces host experts while keeping dense layers on GPU where memory permits. If `-ngl 99` does not fit, reduce it and record the changed placement. Disabling either cache tier changes the method and needs a separate arm.

```sh
GGML_EXPERT_CACHE_MAX=90 \
GGML_EXPERT_RAM_CACHE_MAX=166 \
GGML_OP_OFFLOAD_MIN_BATCH=1 \
./build/bin/llama-server -m "$Q36" -a q36 --mmap \
  -c "$CTX" -ngl 99 --cpu-moe --jinja -fa on -ctk q8_0 -ctv q8_0 \
  -t "$THREADS" --port "$PORT" -lv 4
```

The documented non-cache comparison uses `--no-mmap -ngl 99 --n-cpu-moe N`; `N` must be tuned to match VRAM. That arm changes storage behavior and placement, so label it an end-to-end configuration comparison. For a cache-only ablation, inspect the source and logs to establish which environment flags truly disable each tier on this revision; `GGML_EXPERT_CACHE_MAX=0` is not asserted here as a proven hard-off. The fork logs GPU/RAM/disk hit rates periodically and writes `llama_expert_usage.txt` on exit. Keep these as mandatory evidence. [README methods](https://github.com/Lidenburg/llama.cpp/blob/e85e4d90cd44a8c8332093b0c97a53fa13137f5e/README.md).

## Two Qwen3.6 measurements

**Coherent text.** Use a fresh process and one request at a time. Save visible and reasoning text plus the final hit-rate and wait-time logs. Apply the runbook's minimal output sanity gate and record task completion separately; a server start or first token alone is insufficient.

```sh
curl -fsS "http://127.0.0.1:$PORT/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"q36","messages":[{"role":"user","content":"Write a short Python function to merge sorted lists, then explain its complexity."}],"temperature":0,"max_tokens":512}'
```

**`llama-benchy`.** Use the exact tokenizer matching the GGUF. This [tool](https://github.com/eugr/llama-benchy#usage) measures the same OpenAI-compatible server; its default coherence check stays enabled. A depth/length combination must fit the chosen context. Verify its installed `--help` before execution.

```sh
uv run --project tools/llama-benchy llama-benchy \
  --base-url "http://127.0.0.1:$PORT/v1" \
  --model "$Q36_TOKENIZER" --served-model-name q36 \
  --pp 2048 --tg 512 --depth 0 8192 --runs 3 --warmup-runs 2 \
  --latency-mode generation --concurrency 1 --format json \
  --save-result "$RESULT_JSON"
```

Match GGUF, quant, prompt, token count, and hardware with competitors. Record GPU slots, pinned-RAM slots, actual VRAM/RAM, disk tier accesses, output coherence, and server revision. Report prefill and decode separately: the fork says prefill has not been optimized. The above commands are not performance claims.
