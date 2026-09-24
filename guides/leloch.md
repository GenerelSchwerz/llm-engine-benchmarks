# leloch MoE cache: original and v2

Research draft, 2026-09-24. These are source-reviewed launch templates, **not** built or model-tested commands. Pin a revision, compile with CUDA, compare `build/bin/llama-server --help`, and retain the complete startup and teardown logs before treating any result as evidence. The branches implement an opportunistic CPU-expert cache, not an alternative for a fully GPU-resident model.

| Branch | Reviewed revision | Source evidence |
| --- | --- | --- |
| [Original `moe-cache-pr`](https://github.com/leloch/llama.cpp/tree/moe-cache-pr) | [`a01eb26468a6`](https://github.com/leloch/llama.cpp/tree/a01eb26468a6cb2bf2c3bfd1cc3b5d9e64daefcd) | [`common/arg.cpp`](https://github.com/leloch/llama.cpp/blob/a01eb26468a6cb2bf2c3bfd1cc3b5d9e64daefcd/common/arg.cpp), [`moe-cache.cu`](https://github.com/leloch/llama.cpp/blob/a01eb26468a6cb2bf2c3bfd1cc3b5d9e64daefcd/ggml/src/ggml-cuda/moe-cache.cu) |
| [Revised `moe-cache-v2-pr`](https://github.com/leloch/llama.cpp/tree/moe-cache-v2-pr) | [`e3096b046bb8`](https://github.com/leloch/llama.cpp/tree/e3096b046bb809f7f80bc47801f6579aed1cbc60) | [`common/arg.cpp`](https://github.com/leloch/llama.cpp/blob/e3096b046bb809f7f80bc47801f6579aed1cbc60/common/arg.cpp), [`moe-cache.cu`](https://github.com/leloch/llama.cpp/blob/e3096b046bb809f7f80bc47801f6579aed1cbc60/ggml/src/ggml-cuda/moe-cache.cu), [discussion update](https://github.com/ggml-org/llama.cpp/discussions/24528) |

## Model support and launch recipes

Set `Q36` and `DSV4` to complete GGUF paths, and choose `CTX`, `NGL`, `THREADS`, `PORT` per host. `NGL=99` is only a trial value: inspect placement and reduce it if dense layers, KV, and cache cannot fit. These explicit `--cpu-moe --moe-cache on` recipes deliberately put routed experts in host RAM to make cache use observable. For optimized end-to-end placement, also test `--fit on --moe-cache auto` without explicit `--cpu-moe` or `-ngl`; record the resulting placement. Run each server in a fresh process.

| Model | Original branch | v2 branch | Reason |
| --- | --- | --- | --- |
| Qwen3.6-35B-A3B | Candidate; [original discussion test](https://github.com/ggml-org/llama.cpp/discussions/24528) used Qwen3.6 | Candidate | Both contain Qwen3.5-family model handling. Confirm actual GGUF metadata loads. |
| Qwen3.8-Flash-Next | **Unsupported at reviewed revision** | **Unsupported at reviewed revision** | Neither branch has the `qwen4exp` architecture introduced for this model; do not substitute `qwen3next` by name. |
| DeepSeek V4 Flash | **Unsupported at reviewed revision** | Candidate | v2 contains `deepseek4` model and KV implementations; original does not. Verify the particular GGUF and quant. |

Original Qwen3.6:

```sh
./build/bin/llama-server -m "$Q36" -a q36 -c "$CTX" -ngl "$NGL" \
  --cpu-moe --moe-cache on --jinja -fa on -ctk q8_0 -ctv q8_0 \
  -t "$THREADS" --port "$PORT" -lv 4
```

v2 Qwen3.6:

```sh
./build/bin/llama-server -m "$Q36" -a q36 -c "$CTX" -ngl "$NGL" \
  --cpu-moe --moe-cache on --jinja -fa on -ctk q8_0 -ctv q8_0 \
  -t "$THREADS" --port "$PORT" -lv 4
```

v2 DeepSeek V4 Flash, target only first; add a separate draft/MTP arm only after target-only correctness:

```sh
./build/bin/llama-server -m "$DSV4" -a dsv4 -c "$CTX" -ngl "$NGL" \
  --cpu-moe --moe-cache on --jinja -fa on -ctk q8_0 -ctv q8_0 \
  -t "$THREADS" --port "$PORT" -lv 4
```

The original parser accepts `--moe-cache off|0|auto|on|N` and writes `GGML_CUDA_MOE_CACHE*` environment variables; v2 accepts the same modes into structured parameters. `N` is a positive per-device MiB budget, so vary it after recording the actual pool size. Original [user testing](https://github.com/ggml-org/llama.cpp/discussions/24528) reported `auto` parser failure and ambiguous `0` behavior on an earlier revision; v2 [claims fixes](https://github.com/ggml-org/llama.cpp/discussions/24528). For a hard-off reference on the original, set `GGML_CUDA_MOE_CACHE=0 GGML_CUDA_MOE_CACHE_HOTSET=0`, and verify the logs. Avoid sweeping `GGML_CUDA_MOE_CACHE_MAX_BATCH` without confirming its effect: default original is 1, and v2 logs a bypass above its configured limit. Warm a cache with enough varied decode before measuring; a cold or underfilled pool misstates the result. The cache uses spare VRAM after a reserve, so verify allocated slots and hit counters, not merely the command line. Source: [original parser](https://github.com/leloch/llama.cpp/blob/a01eb26468a6cb2bf2c3bfd1cc3b5d9e64daefcd/common/arg.cpp), [v2 batch gate](https://github.com/leloch/llama.cpp/blob/e3096b046bb809f7f80bc47801f6579aed1cbc60/ggml/src/ggml-cuda/moe-cache.cu).

## Two measurements for each supported model

1. **Coherent text:** With the appropriate server above, run the matching alias (`q36` or `dsv4`) through `/v1/chat/completions`. Preserve the full answer, finish reason, server log, output token count, and timing. Use the same prompt and generation limit across forks; do not treat a successful startup as a pass.

   ```sh
   curl -fsS "http://127.0.0.1:$PORT/v1/chat/completions" \
     -H 'Content-Type: application/json' \
     -d '{"model":"q36","messages":[{"role":"user","content":"Write a short Python function to merge sorted lists, then explain its complexity."}],"temperature":0,"max_tokens":512}'
   ```

   Substitute `dsv4` for the DeepSeek arm. Inspect the output for coherence and task completion. A target-only run must be recorded separately from any MTP run.

2. **`llama-benchy`:** Point the [vendored `llama-benchy`](https://github.com/eugr/llama-benchy) at that same server. `--model` identifies the exact tokenizer; `--served-model-name` identifies the server alias. Substitute `Q36_TOKENIZER`/`dsv4` or `DSV4_TOKENIZER`/`dsv4` per model. These are documented benchy options, but endpoint/model integration is unverified here.

   ```sh
   uv run --project tools/llama-benchy llama-benchy \
     --base-url "http://127.0.0.1:$PORT/v1" \
     --model "$Q36_TOKENIZER" --served-model-name q36 \
     --pp 2048 --tg 512 --depth 0 8192 --runs 3 --warmup-runs 2 \
     --latency-mode generation --concurrency 1 --format json \
     --save-result "$RESULT_JSON"
   ```

Use the same GGUF, quant, context, output length, sampling, GPU set, and tokenizer across competing forks. Capture process RAM and peak VRAM externally. Confirm benchy `--help` and its coherence result at the pinned revision; the benchmark is invalid if cache logs show bypass, no pool, an unsupported model, or incoherent output. See [benchy usage](https://github.com/eugr/llama-benchy#usage).
