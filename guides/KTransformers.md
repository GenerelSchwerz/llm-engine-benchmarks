# Candidate launch and tuning notes

Research snapshot: 2026-09-24. These are **launch templates, not validated benchmark commands**. Pin each exact source SHA, record `llama-server --help`/`llama-cli --help` (or native CLI help), and perform a coherent full request before admitting an arm. Never compare a GGUF run with a native-checkpoint run as if weights and quantization were matched. Replace model paths with the recorded artifacts; verify all model aliases, draft sidecars, and quant support at the pinned revision. Runtime behavior and optimized settings can change after this snapshot.

The three target rows below mean `Q36` = Qwen3.6-35B-A3B, `Q38` = Qwen3.8-Flash-Next, `DV4` = DeepSeek-V4-Flash-0731. A command with `<...>` is deliberately incomplete until the model and hardware manifest supplies that value. In all llama.cpp-based runs, start target-only, then add MTP/DSpark as a separate arm only where the checked-out revision's help and logs prove it works. Log physical GPU placement, actual CPU expert placement, allocated slots, warm-up, cache hits/fills and final decode counters, not just the requested flags.

## [KTransformers](https://github.com/kvcache-ai/ktransformers) — competing runtime, **not a llama.cpp fork**

Research SHA `c40722bf04c494f2492b7eb9e86ef01a4ede45b3`. Its [DeepSeek V4 tutorial](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/DeepSeek-V4-Flash.md) uses an **SGLang + KT-Kernel** stack and native model weights. The repository has a Qwen3-Next guide, but no Q36 or Q38 guide in the current docs tree; do not list those as runnable benchmark arms without independent model support proof.

**Source/install check.** The [pinned DeepSeek V4 tutorial](https://github.com/kvcache-ai/ktransformers/blob/c40722bf04c494f2492b7eb9e86ef01a4ede45b3/doc/en/DeepSeek-V4-Flash.md) lists the native model, dependencies, full SGLang command, and speculative options; use its exact dependency versions and capture `python -m sglang.launch_server --help`. No install or model run has been performed here.


| Model | Launch template / boundary |
| --- | --- |
| Q36 | No verified public command for this exact model; pending support proof. |
| Q38 | No verified public command for this exact model; pending support proof. |
| DV4 | `python -m sglang.launch_server --model <HF-DeepSeek-V4-Flash-0731-dir> --kt-weight-path <same-dir> --kt-method MXFP4 --kt-num-gpu-experts 10 --kt-cpuinfer 60 --kt-threadpool-count 2 --kt-enable-dynamic-expert-update --tensor-parallel-size 1 --context-length 16384 --attention-backend flashinfer --mem-fraction-static 0.85 --disable-shared-experts-fusion --trust-remote-code` is a **condensed template** of the tutorial's single RTX 5090 command; use the full pinned tutorial settings and dependency versions for a reproducer. |

Tune GPU expert count, CPU threads and memory fraction on the target host. The tutorial requires CUDA 12.8+, matching FlashInfer packages >=0.6.9, and a Transformers 4.57.1 pin at its publication state. Optional EAGLE/NextN speculative flags belong in a separate arm. Model and hardware differences prevent direct GGUF speed conclusions.

### Coherent-text and llama-benchy tracks

Use the model-specific server command above, set a local-only port (`--host 127.0.0.1 --port <PORT>` for llama.cpp); for FreeToken/KTransformers use their equivalent bind/port flags and verify `/v1/models`. Run this check for DV4; Q36 and Q38 await support proof, capturing the full response, token usage and server log. Substitute the actual served model id reported by `/v1/models` and the model-specific endpoint port.

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
