# miltos22 wackMall hot-store fork

Research draft, 2026-09-24. Reviewed [`master` at `6cacc5edbb2e`](https://github.com/miltos22/llama.cpp-wackMall-merge-request/tree/6cacc5edbb2e265133491f0e4a5ba9a470f771a2), including [`common/arg.cpp`](https://github.com/miltos22/llama.cpp-wackMall-merge-request/blob/6cacc5edbb2e265133491f0e4a5ba9a470f771a2/common/arg.cpp), [`common/common.cpp`](https://github.com/miltos22/llama.cpp-wackMall-merge-request/blob/6cacc5edbb2e265133491f0e4a5ba9a470f771a2/common/common.cpp), [`common/fit.cpp`](https://github.com/miltos22/llama.cpp-wackMall-merge-request/blob/6cacc5edbb2e265133491f0e4a5ba9a470f771a2/common/fit.cpp), and [`src/llama-expert-hotstore.cpp`](https://github.com/miltos22/llama.cpp-wackMall-merge-request/blob/6cacc5edbb2e265133491f0e4a5ba9a470f771a2/src/llama-expert-hotstore.cpp). Build/CLI/model behavior is unverified; confirm `llama-server --help` and log-resolved placement at this exact revision before using results.

## Model support and choices

| Model | Status | Launch template |
| --- | --- | --- |
| Qwen3.6-35B-A3B | Architecture candidate; GGUF loading unverified | Autofit below |
| Qwen3.8-Flash-Next | **Unsupported**: no `qwen4exp` architecture in this revision | None |
| DeepSeek V4 Flash | Architecture candidate: `deepseek4` and DSV4 KV implementation present; GGUF loading unverified | Autofit below |

Use `--expert-hot-s -1 --fit on` first. `-1` asks fit to size hot slots from free VRAM, then moves all MoE weights to CPU so the hot store has host pointers. **Do not add explicit `-ngl` or `-ncmoe` to this arm**: [`common/common.cpp`](https://github.com/miltos22/llama.cpp-wackMall-merge-request/blob/6cacc5edbb2e265133491f0e4a5ba9a470f771a2/common/common.cpp) says those can abort autofit and turn the cache off. For a manual sweep use `--expert-hot-s N` with positive integer slots; [`common/arg.cpp`](https://github.com/miltos22/llama.cpp-wackMall-merge-request/blob/6cacc5edbb2e265133491f0e4a5ba9a470f771a2/common/arg.cpp) automatically activates `--cpu-moe`. This changes placement; record actual VRAM and fit output before comparing. `--expert-hot-s 0` disables the hot store. The parser also exposes `--expert-sync-period N` (default 1), `--expert-hyst F` (default 1.3, 0 off), `--expert-dwell N` (default 0), and `--expert-pin N` (auto chooses 40% with hot store, 0 otherwise). Treat these as separate tuning sweeps; faster resync can cost transfers and pinned RAM consumes host memory. [Parser](https://github.com/miltos22/llama.cpp-wackMall-merge-request/blob/6cacc5edbb2e265133491f0e4a5ba9a470f771a2/common/arg.cpp), [resync source](https://github.com/miltos22/llama.cpp-wackMall-merge-request/blob/6cacc5edbb2e265133491f0e4a5ba9a470f771a2/src/llama-expert-hotstore.cpp).

Set `Q36` and `DSV4` to exact GGUF paths; set `CTX`, `THREADS`, `PORT` per host. Start target-only, without MTP. The two model-specific server commands use the same cache policy and differ only in model and alias so differences can be traced to the model.

Qwen3.6-35B-A3B:

```sh
./build/bin/llama-server -m "$Q36" -a q36 -c "$CTX" \
  --fit on --expert-hot-s -1 --expert-pin -1 \
  --jinja -fa on -ctk q8_0 -ctv q8_0 -t "$THREADS" \
  --port "$PORT" -lv 4
```

DeepSeek V4 Flash:

```sh
./build/bin/llama-server -m "$DSV4" -a dsv4 -c "$CTX" \
  --fit on --expert-hot-s -1 --expert-pin -1 \
  --jinja -fa on -ctk q8_0 -ctv q8_0 -t "$THREADS" \
  --port "$PORT" -lv 4
```

For a manual positive-slot arm, replace `--expert-hot-s -1` with a measured `N`, then benchmark several `N` values that fit the card. Manual slots imply `--cpu-moe` in argument post-processing. `--mmap`/`--no-mmap` and host paging affect the cold tier; hold them constant between manual-slot comparisons. Inspect hot-store allocation and hit logs before calling an arm cache-enabled. DeepSeek's special KV and quant behavior must be checked with this build; no model-specific tuning claim is made from source alone.

## Two measurements for each candidate model

**Coherent text:** Launch the relevant server in a fresh process. Substitute `q36` or `dsv4` in the request. Keep the complete response, finish reason, generated count, and logs; compare one coherent prompt before throughput.

```sh
curl -fsS "http://127.0.0.1:$PORT/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"q36","messages":[{"role":"user","content":"Write a short Python function to merge sorted lists, then explain its complexity."}],"temperature":0,"max_tokens":512}'
```

**`llama-benchy`:** For Qwen3.6, use `TOKENIZER="$Q36_TOKENIZER" ALIAS=q36`; for DeepSeek V4 Flash, `TOKENIZER="$DSV4_TOKENIZER" ALIAS=dsv4`. The [benchy arguments](https://github.com/eugr/llama-benchy#usage) are source-documented; endpoint behavior remains unverified until an actual model run. Use an exact tokenizer and context depth within `CTX`.

```sh
uv run --project tools/llama-benchy llama-benchy \
  --base-url "http://127.0.0.1:$PORT/v1" \
  --model "$TOKENIZER" --served-model-name "$ALIAS" \
  --pp 2048 --tg 512 --depth 0 8192 --runs 3 --warmup-runs 2 \
  --latency-mode generation --concurrency 1 --format json \
  --save-result "$RESULT_JSON"
```

Keep fixed prompts, output length, model quant, context, GPU set, and host state across engines. Report prefill and decode, actual VRAM/RAM, hot-store slots/hits, and coherent output. Cache-off, autofit, and manual-slot results are distinct configurations; `-1` silently resolving to zero is a failed cache arm, not a slow cache.
