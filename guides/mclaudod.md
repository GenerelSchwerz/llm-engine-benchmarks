# Candidate launch and tuning notes

Research snapshot: 2026-09-24. These are **launch templates, not validated benchmark commands**. Pin each exact source SHA, record `llama-server --help`/`llama-cli --help` (or native CLI help), and perform a coherent full request before admitting an arm. Never compare a GGUF run with a native-checkpoint run as if weights and quantization were matched. Replace model paths with the recorded artifacts; verify all model aliases, draft sidecars, and quant support at the pinned revision. Runtime behavior and optimized settings can change after this snapshot.

The three target rows below mean `Q36` = Qwen3.6-35B-A3B, `Q38` = Qwen3.8-Flash-Next, `DV4` = DeepSeek-V4-Flash-0731. A command with `<...>` is deliberately incomplete until the model and hardware manifest supplies that value. In all llama.cpp-based runs, start target-only, then add MTP/DSpark as a separate arm only where the checked-out revision's help and logs prove it works. Log physical GPU placement, actual CPU expert placement, allocated slots, warm-up, cache hits/fills and final decode counters, not just the requested flags.

## [mclaudod/llama.cpp `moe-hot-cache`](https://github.com/mclaudod/llama.cpp/tree/moe-hot-cache)

Pinned research SHA `b5516876f10c7ceea1ba4695cdcdc80f71c71c5f`. This is a CUDA hot-expert cache for **host-resident** routed experts. Its [configuration document](https://github.com/mclaudod/llama.cpp/blob/moe-hot-cache/docs/backend/CUDA-MOE-CACHE.md) says `--moe-cache auto` needs two selected CUDA devices (compute capability 8.0+); `on` or a MiB budget can use one selected device (7.0+). `auto` can stay dormant if the model fits VRAM. Trace logging (`-lv 4`) and an `[moe-cache] enabled` pool message are required to establish that the cache actually ran. Leave `GGML_OP_OFFLOAD_MIN_BATCH` above decode batch width; setting it to 1 can bypass the CPU hit/miss split. Reserve and max-node-width are controlled by `GGML_CUDA_MOE_CACHE_RESERVE_MB` and `GGML_CUDA_MOE_CACHE_MAX_BATCH`; do not change them without a separate arm.

**Source/compile check.** [`common/arg.cpp`](https://github.com/mclaudod/llama.cpp/blob/b5516876f10c7ceea1ba4695cdcdc80f71c71c5f/common/arg.cpp) parses `--moe-cache`; [`docs/backend/CUDA-MOE-CACHE.md`](https://github.com/mclaudod/llama.cpp/blob/b5516876f10c7ceea1ba4695cdcdc80f71c71c5f/docs/backend/CUDA-MOE-CACHE.md) defines modes and diagnostics. Build candidate: `cmake -S . -B build -DGGML_CUDA=ON && cmake --build build -j`, then capture `build/bin/llama-server --help`. Build has not been run here.


| Model | Target-only launch template / support boundary |
| --- | --- |
| Q36 | `llama-server -m <Q36.gguf> -ngl auto --cpu-moe --moe-cache on -fa on -c 8192 -np 1 -lv 4` — the docs report Q36 Q4_K_XL cache tests. For two eligible GPUs, compare `--fit on --moe-cache auto` with explicit placement. |
| Q38 | `llama-server -m <Q38.gguf> -ngl auto --cpu-moe --moe-cache on -fa on -c 8192 -np 1 -lv 4` is a **candidate only**. The cache design is generic, but the branch's published guide did not establish Q38 model-load compatibility; gate on a real load, output and pool log. |
| DV4 | `llama-server -m <DV4.gguf> --fit on --moe-cache auto -fa on -c 8192 -np 1 -lv 4` on two eligible CUDA devices. The docs also give a four-GPU DSpark command using `-md <dspark.gguf> --spec-type draft-dspark --spec-draft-n-max 5`; keep that as a distinct speculative arm. |

Tune `auto`, `on`, and fixed MiB budgets against the same placement and available VRAM. The documented default reserve is 3072 MiB per device; a fixed budget is a cap, not guaranteed allocation. Tests should include cache-off, warm and cold decode. Include an OOM and memory-fit gate for DeepSeek; model load alone is insufficient proof.

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
