# Candidate launch and tuning notes

Research snapshot: 2026-09-24. These are **launch templates, not validated benchmark commands**. Pin each exact source SHA, record `llama-server --help`/`llama-cli --help` (or native CLI help), and perform a coherent full request before admitting an arm. Never compare a GGUF run with a native-checkpoint run as if weights and quantization were matched. Replace model paths with the recorded artifacts; verify all model aliases, draft sidecars, and quant support at the pinned revision. Runtime behavior and optimized settings can change after this snapshot.

The three target rows below mean `Q36` = Qwen3.6-35B-A3B, `Q38` = Qwen3.8-Flash-Next, `DV4` = DeepSeek-V4-Flash-0731. A command with `<...>` is deliberately incomplete until the model and hardware manifest supplies that value. In all llama.cpp-based runs, start target-only, then add MTP/DSpark as a separate arm only where the checked-out revision's help and logs prove it works. Log physical GPU placement, actual CPU expert placement, allocated slots, warm-up, cache hits/fills and final decode counters, not just the requested flags.

## [FreeToken](https://github.com/FlashML-org/FreeToken) — competing runtime, **not a llama.cpp fork**

Research SHA `cee23bf44a86e48d70f8fda3ca3b6d4d9890072e`. FreeToken takes **native Hugging Face checkpoints**, not the same GGUF used by llama.cpp; record checkpoint, dtype and quant provenance. The [model list](https://github.com/FlashML-org/FreeToken/blob/main/docs/models.md) names all three models; the [CLI](https://github.com/FlashML-org/FreeToken/blob/main/docs/cli.md) now uses `--moe-strategy` (`--moe-backend` is older spelling). It supports `fused`, `offload`, `cpu`, `hybrid`, or `auto`; `auto` uses offload or profile-guided hybrid. `ft bench bw` calibrates hybrid on the particular machine. `--moe-cache-size`, `--moe-cache-rate` and `--moe-cache-auto` are mutually exclusive sizing forms.

**Source/install check.** [`python/freetoken/server/args.py`](https://github.com/FlashML-org/FreeToken/blob/cee23bf44a86e48d70f8fda3ca3b6d4d9890072e/python/freetoken/server/args.py) defines CLI parsing (`--host`, `--port`, `--moe-strategy`); [`docs/quickstart.md`](https://github.com/FlashML-org/FreeToken/blob/cee23bf44a86e48d70f8fda3ca3b6d4d9890072e/docs/quickstart.md) covers installation. Capture `ft serve --help` in a pinned Python environment. No install or model run has been performed here.


| Model | Launch template / boundary |
| --- | --- |
| Q36 | `ft serve --model <HF-Qwen3.6-35B-A3B-NVFP4-dir> --moe-strategy offload --moe-cache-auto`; compare `cpu` and calibrated `hybrid` as separate arms. |
| Q38 | `ft serve --model <HF-Qwen3.8-Flash-Next-NVFP4-dir> --moe-strategy offload --moe-cache-auto`; budget its large PLE table, and validate current `--ple-backend` help (`disk` is documented in release notes). |
| DV4 | `ft serve --model <HF-DeepSeek-V4-Flash-0731-dir> --moe-strategy offload --moe-cache-auto`; preserve the checkpoint's `inference/config.json` subdir. |

Check `ft serve --help` at the pinned SHA: the model guide still shows the older `--moe-backend` spelling while the CLI guide prefers `--moe-strategy`. Use one checkpoint across FreeToken strategies. Report native-vs-GGUF comparisons as observational unless weights, quantization and output equivalence are established. Do not assume FreeToken has the same MTP path as a llama.cpp fork at this revision.

### Coherent-text and llama-benchy tracks

Use the model-specific server command above, set a local-only port (`--host 127.0.0.1 --port <PORT>` for llama.cpp); use FreeToken `--host 127.0.0.1 --port <PORT>` (defined in its pinned CLI parser) and verify `/v1/models`. Run this check **for each model and optimized arm**, capturing the full response, token usage and server log. Substitute the actual served model id reported by `/v1/models` and the model-specific endpoint port.

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
