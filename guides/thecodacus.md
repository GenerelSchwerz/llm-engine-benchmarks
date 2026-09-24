# Candidate launch and tuning notes

Research snapshot: 2026-09-24. These are **launch templates, not validated benchmark commands**. Pin each exact source SHA, record `llama-server --help`/`llama-cli --help` (or native CLI help), and perform a coherent full request before admitting an arm. Never compare a GGUF run with a native-checkpoint run as if weights and quantization were matched. Replace model paths with the recorded artifacts; verify all model aliases, draft sidecars, and quant support at the pinned revision. Runtime behavior and optimized settings can change after this snapshot.

The three target rows below mean `Q36` = Qwen3.6-35B-A3B, `Q38` = Qwen3.8-Flash-Next, `DV4` = DeepSeek-V4-Flash-0731. A command with `<...>` is deliberately incomplete until the model and hardware manifest supplies that value. In all llama.cpp-based runs, start target-only, then add MTP/DSpark as a separate arm only where the checked-out revision's help and logs prove it works. Log physical GPU placement, actual CPU expert placement, allocated slots, warm-up, cache hits/fills and final decode counters, not just the requested flags.

## [thecodacus/llama.cpp `perf`](https://github.com/thecodacus/llama.cpp/tree/perf)

Research SHA `27c54b4bbcefadedcec6397477cc2e866c1db716`. The [branch README](https://github.com/thecodacus/llama.cpp/blob/perf/README.md) documents a **profile-seeded** cache: first run `llama-moe-trace`, then provide the merged CSV with `--moe-cache-profile` and `--moe-cache-slots`. This is distinct from the old `moe-cache` branch (`--moe-expert-cache-size`). It also documents `GGML_CUDA_REGISTER_HOST=1` and `GGML_SCHED_PREFETCH_EXPERTS=1` for pinned host weights and async prefetch. Confirm these features coexist in the exact pinned tree and check help before running; the README points to feature branches as well.

```sh
MOE_TRACE_OUT=<model>-code.csv ./build/bin/llama-moe-trace -m <model.gguf> -ngl 99 -ncmoe 99 -fa 1 -c 4096 -n 512 -p '<coding prompt>'
MOE_TRACE_OUT=<model>-chat.csv ./build/bin/llama-moe-trace -m <model.gguf> -ngl 99 -ncmoe 99 -fa 1 -c 4096 -n 512 -p '<chat prompt>'
cat <model>-code.csv <model>-chat.csv > <model>-merged.csv
GGML_CUDA_REGISTER_HOST=1 GGML_SCHED_PREFETCH_EXPERTS=1 ./build/bin/llama-server -m <model.gguf> -ngl 99 -ncmoe 99 -fa 1 --moe-cache-profile <model>-merged.csv --moe-cache-slots <slots>
```

**Source/compile check.** [`common/arg.cpp`](https://github.com/thecodacus/llama.cpp/blob/27c54b4bbcefadedcec6397477cc2e866c1db716/common/arg.cpp) parses `--moe-cache-profile` and `--moe-cache-slots`; [`ggml/src/ggml-backend.cpp`](https://github.com/thecodacus/llama.cpp/blob/27c54b4bbcefadedcec6397477cc2e866c1db716/ggml/src/ggml-backend.cpp) reads the scheduler prefetch variable. Build candidate: `cmake -S . -B build -DGGML_CUDA=ON && cmake --build build -j`. Validate that the trace executable and server flags exist in this same build. No build has been run here.


| Model | Model-specific starting point / boundary |
| --- | --- |
| Q36 | README reports Q4_K_M at 124 slots target-only, 112 with MTP, 88 with async CPU split on RTX 3060 12GB. Start below the measured VRAM ceiling; profile the exact Q36 GGUF and prompts. |
| Q38 | README reports UD-IQ3_XXS at 56 slots **with MTP**. First validate Q38 target-only with its own trace; then run the MTP sidecar as a separate arm, if the pinned CLI supports it. |
| DV4 | README lists `deepseek2` among supported architectures but provides no DV4 benchmark recipe. Treat DV4 as conditional on the pinned model loader and trace tool; no recommended slots can be transferred from Q36/Q38. |

The README says cache allocation is all-or-nothing and recommends roughly 900 MiB runtime VRAM headroom after the pack. Inspect `init_moe_expert_cache` logs to prove allocation; an oversized pack can silently fall back to baseline after warning. Do not use an old profile from another model or quant.

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
