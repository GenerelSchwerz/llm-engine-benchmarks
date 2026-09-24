# Candidate launch and tuning notes

Research snapshot: 2026-09-24. These are **launch templates, not validated benchmark commands**. Pin each exact source SHA, record `llama-server --help`/`llama-cli --help` (or native CLI help), and perform a coherent full request before admitting an arm. Never compare a GGUF run with a native-checkpoint run as if weights and quantization were matched. Replace model paths with the recorded artifacts; verify all model aliases, draft sidecars, and quant support at the pinned revision. Runtime behavior and optimized settings can change after this snapshot.

The three target rows below mean `Q36` = Qwen3.6-35B-A3B, `Q38` = Qwen3.8-Flash-Next, `DV4` = DeepSeek-V4-Flash-0731. A command with `<...>` is deliberately incomplete until the model and hardware manifest supplies that value. In all llama.cpp-based runs, start target-only, then add MTP/DSpark as a separate arm only where the checked-out revision's help and logs prove it works. Log physical GPU placement, actual CPU expert placement, allocated slots, warm-up, cache hits/fills and final decode counters, not just the requested flags.

## [spiritbuun/buun-llama-cpp](https://github.com/spiritbuun/buun-llama-cpp)

Research SHA `2ef0317dd91e2ca4732fffa456dc5e2311db41c7`. **Yes, buun has an MoE cache**, credited to leloch with additional fit/soft mode and CPU-overlap policy. The [README's model recipes](https://github.com/spiritbuun/buun-llama-cpp#deepseek-v4-flash-and-qwen38-flash-next--moe-cache) and [cache guide](https://github.com/spiritbuun/buun-llama-cpp/blob/master/docs/backend/CUDA-MOE-CACHE.md) recommend `--fit on --moe-cache auto`; it may deliberately leave experts in RAM to use spare VRAM as cache. `--moe-cache on` forces canonical CPU experts; `soft` partially evicts experts. Cache participation must be confirmed with `-lv 4` and `[moe-cache] enabled`.

**Source/compile check.** [`common/arg.cpp`](https://github.com/spiritbuun/buun-llama-cpp/blob/2ef0317dd91e2ca4732fffa456dc5e2311db41c7/common/arg.cpp) parses mode, expert-parallel and CPU-overlap flags. Build candidate: `cmake -S . -B build -DGGML_CUDA=ON && cmake --build build -j`, then capture server help and logs. The [cache guide](https://github.com/spiritbuun/buun-llama-cpp/blob/2ef0317dd91e2ca4732fffa456dc5e2311db41c7/docs/backend/CUDA-MOE-CACHE.md) gives the eligibility criteria. No build has been run here.


| Model | Launch template / boundary |
| --- | --- |
| Q36 | `./build/bin/llama-server -m <Q36.gguf> -ngl auto -fa on -c 8192 -np 1 --fit on --moe-cache auto -lv 4`; Q36 is not given a separate cache recipe, so check that it actually spills experts and creates pools. |
| Q38 | `./build/bin/llama-server -m <Q38.gguf> -ngl auto -sm layer -fa on -c 8192 -np 1 --vbr-entry t8 --fit on --moe-cache auto -lv 4`. README also shows `-md <official-shared-MTP.gguf> --spec-type draft-mtp`; keep that as a distinct arm. |
| DV4 | `./build/bin/llama-server -m <DV4.gguf> -ngl auto -sm layer -fa on -c 8192 -np 1 --vbr-entry t8 --fit on --moe-cache auto -lv 4`; on 2+ GPUs test `--moe-cache-expert-parallel auto` separately. README has a separate DSpark recipe. |

For Q38/DV4, compare VBR entry `t8` with fixed KV precision while accounting for quality; `t4` is a more aggressive quality tradeoff. First leave reserve, threads and placement automatic. Then test CPU overlap `auto` versus `0` and possibly `1..8`, expert-parallel fanout, and `soft` separately. The README warns layer splitting was better than tensor splitting for its CPU-expert case; verify on the benchmark host. The fork is highly experimental, so exact help and startup logs are especially important.

### Coherent-text and llama-benchy tracks

Use the model-specific server command above, set a local-only port (`--host 127.0.0.1 --port <PORT>` for llama.cpp); for FreeToken/KTransformers use their equivalent bind/port flags and verify `/v1/models`. Run this check **for each model and optimized arm**, capturing the full response, token usage and server log. Substitute the actual served model id reported by `/v1/models` and the model-specific endpoint port.

```sh
curl -fsS http://127.0.0.1:<PORT>/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"<SERVED_MODEL>","messages":[{"role":"user","content":"Explain how a ring buffer handles wraparound, then provide a short C++ example."}],"temperature":0,"max_tokens":512,"stream":false}' \
  > <RUN_DIR>/coherence.json
```

Inspect the answer for completion and coherence; check generated-token count and errors. Repeat with a longer, shared prompt for sustained decode. The benchmark track uses the same server after warmup:

```sh
llama-benchy --base-url http://127.0.0.1:<PORT>/v1 \
  --model <SERVED_MODEL> --tokenizer <MATCHING_HF_TOKENIZER_OR_LOCAL_PATH> \
  --pp 2048 --tg 128 512 --concurrency 1 --runs 3 --warmup-runs 1 \
  --latency-mode generation --format json --save-result <RUN_DIR>/benchy.json
```

This uses [llama-benchy](https://github.com/eugr/llama-benchy)'s OpenAI-compatible chat endpoint; it is **not** `llama-bench`. Check tokenizer/template mapping, actual output lengths, context behavior and each server's response to the tool's prompt/cache settings before treating results as matched. `--exact-tg` uses `min_tokens` and `ignore_eos`; omit it until this server is confirmed to honor both. Keep the tool's own revision and raw JSON in the run manifest.
