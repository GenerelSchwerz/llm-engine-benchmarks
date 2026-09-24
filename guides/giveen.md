# giveen TurboQuant MoE-cache branch

Research draft, 2026-09-24. The older `moe-cache` branch is absent from the current public branch list. The available [giveen `feature/turboquant-kv-cache` branch](https://github.com/giveen/llama-cpp-turboquant/tree/feature/turboquant-kv-cache) was reviewed at [`bcc337d69f40`](https://github.com/giveen/llama-cpp-turboquant/tree/bcc337d69f4065cb37f2aa5bd17c34fed87bd6f4) (2026-09-19). Its [parser](https://github.com/giveen/llama-cpp-turboquant/blob/bcc337d69f4065cb37f2aa5bd17c34fed87bd6f4/common/arg.cpp), [MoE cache guide](https://github.com/giveen/llama-cpp-turboquant/blob/bcc337d69f4065cb37f2aa5bd17c34fed87bd6f4/docs/backend/MOE-CACHE.md), and [KV guide](https://github.com/giveen/llama-cpp-turboquant/blob/bcc337d69f4065cb37f2aa5bd17c34fed87bd6f4/docs/KV-cache-quantization.md) were inspected. This is a historical contributor revision of the TurboQuant line, not a claim of an independent current design. Keep it as a separately pinned benchmark arm only if its exact changes matter. No build or model run has validated the commands.

## Source-supported settings

The parser supports `--moe-cache off|0|auto|soft|on|N`, where `N` is a per-device MiB cap. `auto` plus `--fit on` is the initial placement policy; it may leave cache off when the model fits wholly in VRAM. `on` forces CPU-resident routed experts and disables repacking; `soft` prefers stock placement until experts need eviction. Forced `--cpu-moe`, `-ngl`, and `-ncmoe` can override cache-aware fit, so record resolved placement and weight repacking. The cache's default reserve is 3072 MiB and `auto` needs an adequate pool; an active run should report `[moe-cache] enabled` and nonzero allocated slots. Warm decode before measuring and preserve hit/miss/fallback counters. [Parser](https://github.com/giveen/llama-cpp-turboquant/blob/bcc337d69f4065cb37f2aa5bd17c34fed87bd6f4/common/arg.cpp), [cache implementation guide](https://github.com/giveen/llama-cpp-turboquant/blob/bcc337d69f4065cb37f2aa5bd17c34fed87bd6f4/docs/backend/MOE-CACHE.md).

| Model | Source support | Specific optimization check |
| --- | --- | --- |
| Qwen3.6-35B-A3B | `qwen35` family present; GGUF untested | Test automatic placement, then a fixed host-expert arm if auto is dormant. |
| Qwen3.8-Flash-Next | `qwen4exp` architecture present; GGUF untested | Run target-only first; MTP uses another scheduler and needs distinct proof. |
| DeepSeek V4 Flash | `deepseek4` present; GGUF untested | Run target-only first; test DSpark separately and inspect KV allocation. |

Set `Q36`, `Q38`, `DSV4` to complete GGUF paths, plus `CTX`, `THREADS`, `PORT`. The three server commands are research templates for the same cache policy and q8_0 KV. Choose context and hardware so fit leaves cache capacity; do not add `-ngl` to this autofit arm without recording its effect.

Qwen3.6-35B-A3B:

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

After the automatic arm, use `--cpu-moe -ngl N --moe-cache on` or a positive MiB cap to study cache behavior at controlled host-expert placement. Pair it with `--moe-cache off` and consider `--repack off` in both arms to limit repacking differences; record the resulting absolute-speed cost. This source guide describes cache as decode-oriented and a first-token cold-pool effect, so report prefill, TTFT, and warmed decode separately. TurboQuant `-ctv turbo3` is a separate KV quantization experiment: it changes memory and possibly quality, and [the KV guide](https://github.com/giveen/llama-cpp-turboquant/blob/bcc337d69f4065cb37f2aa5bd17c34fed87bd6f4/docs/KV-cache-quantization.md) notes that MLA has no separate V cache. Verify its actual model-specific behavior before comparing to q8_0.

## Two measurements per model

**Coherent text:** Launch a fresh server for each model and substitute its alias (`q36`, `q38`, `dsv4`). Keep the full answer, finish reason, and logs. Do not count a startup or first token as a successful run.

```sh
curl -fsS "http://127.0.0.1:$PORT/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"q36","messages":[{"role":"user","content":"Write a short Python function to merge sorted lists, then explain its complexity."}],"temperature":0,"max_tokens":512}'
```

**`llama-benchy`:** For each model, set `TOKENIZER` to its exact tokenizer and `ALIAS` to the server name (`q36`, `q38`, `dsv4`). Validate the installed [benchy CLI](https://github.com/eugr/llama-benchy#usage) and server API before recording a result. Its default coherence check should pass.

```sh
uv run --project tools/llama-benchy llama-benchy \
  --base-url "http://127.0.0.1:$PORT/v1" \
  --model "$TOKENIZER" --served-model-name "$ALIAS" \
  --pp 2048 --tg 512 --depth 0 8192 --runs 3 --warmup-runs 2 \
  --latency-mode generation --concurrency 1 --format json \
  --save-result "$RESULT_JSON"
```

Hold model quant, context, KV types, GPU set, prompts, output length, and server limits constant against other forks. Record actual placement, VRAM/RAM, cache engagement, finish reason, TTFT, prefill, decode, and cache counters. The source review does not establish a performance advantage over TheTom's newer branch.
