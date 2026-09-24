# Candidate launch and tuning notes

Research snapshot: 2026-09-24. These are **launch templates, not validated benchmark commands**. Pin each exact source SHA, record `llama-server --help`/`llama-cli --help` (or native CLI help), and perform a coherent full request before admitting an arm. Never compare a GGUF run with a native-checkpoint run as if weights and quantization were matched. Replace model paths with the recorded artifacts; verify all model aliases, draft sidecars, and quant support at the pinned revision. Runtime behavior and optimized settings can change after this snapshot.

The three target rows below mean `Q36` = Qwen3.6-35B-A3B, `Q38` = Qwen3.8-Flash-Next, `DV4` = DeepSeek-V4-Flash-0731. A command with `<...>` is deliberately incomplete until the model and hardware manifest supplies that value. In all llama.cpp-based runs, start target-only, then add MTP/DSpark as a separate arm only where the checked-out revision's help and logs prove it works. Log physical GPU placement, actual CPU expert placement, allocated slots, warm-up, cache hits/fills and final decode counters, not just the requested flags.

## [Atomic-Germ/Guanaco](https://github.com/Atomic-Germ/Guanaco)

Research SHA `8364229686d74ec7495d2e726268bb329e759e84`. Guanaco is a **llama.cpp patch/build wrapper for Linux SSD expert streaming**, not a VRAM cache. Build from this repo root with `git submodule update --init`, `cmake -B build -S .`, and `cmake --build build`; building its `llama.cpp` submodule directly omits the patch. The [README](https://github.com/Atomic-Germ/Guanaco#readme) documents `--load-mode streaming` and `--guanaco-max-experts N` (resident hot experts per fused tensor). It may be a separate memory-constrained tier rather than a fair same-RAM speed arm.

**Source/compile check.** [`patches/common-arg.cpp.patch`](https://github.com/Atomic-Germ/Guanaco/blob/8364229686d74ec7495d2e726268bb329e759e84/patches/common-arg.cpp.patch) adds the max-experts flag; the [README build instructions](https://github.com/Atomic-Germ/Guanaco/blob/8364229686d74ec7495d2e726268bb329e759e84/README.md) require configure/build from Guanaco's root. Confirm the submodule SHA and successful patch application before comparing. No build has been run here.


| Model | Launch template / boundary |
| --- | --- |
| Q36 | `./build/bin/llama-server -m <Q36.gguf> -ngl 0 -c 8192 --load-mode streaming --guanaco-max-experts 12`; Q36 is described in the README. |
| Q38 | Same template with `<Q38.gguf>`, **conditional** on the patched submodule supporting the exact model/quant and detecting fused expert tensors. An [Atomic-Germ Q38 branch](https://github.com/Atomic-Germ/llama.cpp/tree/feat/qwen38-moe-gpu-pill-streaming) is a separate UMA/Vulkan/HIP candidate, not Guanaco. |
| DV4 | Same template with `<DV4.gguf>`, **unverified**; do not admit until model load, expert detection, and full output succeed. |

Compare `--guanaco-max-experts` values against actual RSS and page faults; `GUANACO_PILOT=0` disables lookahead, `GUANACO_PILOT_MASS` tunes its I/O, and `GUANACO_IMATRIX=0` disables prior-based pinning. Keep NVMe, Linux page-cache state and RAM cap recorded. Do not interpret disk-streaming results as CUDA expert-cache results.

### Separate UMA branch: `Atomic-Germ/llama.cpp`

The [public branch](https://github.com/Atomic-Germ/llama.cpp/tree/feat/qwen38-moe-gpu-pill-streaming) is pinned here at `cd252aa7e0e01d74647eeaa3c9634ff23979ea06`. Its [`common/arg.cpp`](https://github.com/Atomic-Germ/llama.cpp/blob/cd252aa7e0e01d74647eeaa3c9634ff23979ea06/common/arg.cpp) defines `--gpu-pill` / `--no-gpu-pill` for UMA KV writeback, and [`src/llama-context.cpp`](https://github.com/Atomic-Germ/llama.cpp/blob/cd252aa7e0e01d74647eeaa3c9634ff23979ea06/src/llama-context.cpp) shows it requires operation offload. The author [reported](https://github.com/ggml-org/llama.cpp/discussions/24528) this branch worked only with UMA, Vulkan or HIP, and had been confirmed for Q36/Q38. This is **not Guanaco's CPU/NVMe resident-expert streaming mode**; benchmark it as a distinct UMA cohort.

| Model | UMA branch research template / boundary |
| --- | --- |
| Q36 | `./build/bin/llama-server -m <Q36.gguf> -ngl auto -fa on -c 8192 --gpu-pill`; build with `-DGGML_VULKAN=ON` or `-DGGML_HIP=ON` for the actual UMA device. Compare `--no-gpu-pill` in the same revision. |
| Q38 | Same command with `<Q38.gguf>`; compare pill on/off and verify model-specific logs and coherent output. |
| DV4 | No author-confirmed DV4 support or speed result for this branch; pending load and correctness proof. |

The coherent-text and llama-benchy tracks below apply to this UMA server as well, with its own run ID and hardware manifest.

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
