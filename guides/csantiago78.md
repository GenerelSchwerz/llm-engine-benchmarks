# Candidate launch and tuning notes

Research snapshot: 2026-09-24. These are **launch templates, not validated benchmark commands**. Pin each exact source SHA, record `llama-server --help`/`llama-cli --help` (or native CLI help), and perform a coherent full request before admitting an arm. Never compare a GGUF run with a native-checkpoint run as if weights and quantization were matched. Replace model paths with the recorded artifacts; verify all model aliases, draft sidecars, and quant support at the pinned revision. Runtime behavior and optimized settings can change after this snapshot.

The three target rows below mean `Q36` = Qwen3.6-35B-A3B, `Q38` = Qwen3.8-Flash-Next, `DV4` = DeepSeek-V4-Flash-0731. A command with `<...>` is deliberately incomplete until the model and hardware manifest supplies that value. In all llama.cpp-based runs, start target-only, then add MTP/DSpark as a separate arm only where the checked-out revision's help and logs prove it works. Log physical GPU placement, actual CPU expert placement, allocated slots, warm-up, cache hits/fills and final decode counters, not just the requested flags.

## [csantiago78 PR #27861](https://github.com/ggml-org/llama.cpp/pull/27861)

Original public head: [`csantiago78:moe-expert-cache`](https://github.com/csantiago78/llama.cpp/tree/moe-expert-cache), `bccbacdb8945680f1cfc7e6bffd1e59014705750`. It adds `--moe-expert-cache N` **slots per host-offloaded expert layer** and `--moe-expert-cache-inserts N` uploads per layer/step. Start with `--cpu-moe` or an explicit CPU expert override; inspect actual slot memory, since N is not MiB. [PR tests](https://github.com/ggml-org/llama.cpp/pull/27861) include Q38 and Q36, with substantial differences by hardware, quant, slot count and upload rate.

**Source/compile check.** [`common/arg.cpp`](https://github.com/csantiago78/llama.cpp/blob/bccbacdb8945680f1cfc7e6bffd1e59014705750/common/arg.cpp) parses the two cache flags; [PR #27861](https://github.com/ggml-org/llama.cpp/pull/27861) documents the design. Build candidate with the backend under test (`-DGGML_CUDA=ON` or `-DGGML_VULKAN=ON`): `cmake -S . -B build -DGGML_CUDA=ON && cmake --build build -j`. No build or CLI help has been run here.


| Model | Target-only launch template / support boundary |
| --- | --- |
| Q36 | `llama-server -m <Q36.gguf> -ngl auto --cpu-moe -fa on -c 8192 -np 1 --moe-expert-cache <slots> --moe-expert-cache-inserts <uploads>`; sweep 0, 48, 96 slots only if each fits and keep uploads fixed. The PR cites 96 slots in a separately patched tree, not an original-PR optimum. |
| Q38 | Same command with `<Q38.gguf>`; the PR cites 48 slots / 2 inserts on a single GPU, while other users report 84 slots / 4 inserts. Verify this branch actually loads the exact Q38 quant before including it. |
| DV4 | The cache API is generic, but no clean original-head DV4 command was established in the PR; **conditional** on model support and a successful full request. Use the same target-only template with `<DV4.gguf>`, without assuming the reported Q38 settings transfer. |

A Q38 MTP configuration that combines this PR with a newer MTP base and follow-up patches is a distinct source revision. `LLAMA_MOE_CACHE_MAX_TOKENS=3` belongs to a follow-up patch. That variable is from a **follow-up small-batch patch**, not the original PR. Its 16 setting triggered an illegal-memory-access failure in one test; do not copy the combined command into the original-head recipe. Version the patch stack as a separate candidate, record every patch SHA, and validate its `--help` and graph-width behavior.

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
