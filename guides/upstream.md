# Upstream llama.cpp baseline

Source: [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp); reviewed commit [`84e76d8a23162eca70490da131945ebec1f09bf4`](https://github.com/ggml-org/llama.cpp/tree/84e76d8a23162eca70490da131945ebec1f09bf4). Status: **source-reviewed research draft**. No build, `--help` capture or model run has been performed here. Preserve this exact revision as the baseline; a moving `master` would make later fork comparisons uninterpretable.

## Build and controls

For CUDA, candidate build: `cmake -S . -B build -DGGML_CUDA=ON && cmake --build build -j`. Capture compiler, CUDA toolkit, driver, GPU architecture, binary hash and `build/bin/llama-server --help`. The [`common/arg.cpp` parser](https://github.com/ggml-org/llama.cpp/blob/84e76d8a23162eca70490da131945ebec1f09bf4/common/arg.cpp) defines `--fit`, `--cpu-moe`, `--n-cpu-moe`, `-ngl`, `--flash-attn`, KV types, `--split-mode`, `--tensor-split`, draft flags, and load mode. [`src/llama-arch.cpp`](https://github.com/ggml-org/llama.cpp/blob/84e76d8a23162eca70490da131945ebec1f09bf4/src/llama-arch.cpp) lists `qwen35moe`, `qwen4exp`, and `deepseek4`; this establishes parser/model code presence, **not** successful loading of each supplied GGUF or quant.

Use identical model files, context, prompt, batch/ubatch, sampling, output budget, GPU selection, and KV types in the fork's cache-off arm where possible. Keep `--fit on` and forced `--cpu-moe` as **separate placement arms**. `-ngl auto` can choose a different effective placement across revisions: preserve tensor placement and VRAM logs before attributing any delta to the cache. Start at `-c 8192 -np 1 -fa on -ctk q8_0 -ctv q8_0`; test larger context, different KV types and multi-GPU splits separately. Do not silently infer cache parity from requested flags.

## Model commands (target only)

Substitute absolute GGUF paths and a unique port. The aliases are also the served model IDs for the request examples below.

| Model | Baseline research command | Notes |
| --- | --- | --- |
| Qwen3.6-35B-A3B | `./build/bin/llama-server -m <Q36.gguf> -a q36 -ngl auto --fit on -c 8192 -np 1 -fa on -ctk q8_0 -ctv q8_0 --host 127.0.0.1 --port <PORT>` | Compare this automatic-fit placement with `--cpu-moe -ngl auto` when the fork cache requires host experts. Record actual expert placement in both. |
| Qwen3.8-Flash-Next | `./build/bin/llama-server -m <Q38.gguf> -a q38 -ngl auto --fit on -c 8192 -np 1 -fa on -ctk q8_0 -ctv q8_0 --host 127.0.0.1 --port <PORT>` | `qwen4exp` target architecture exists in this pinned source. **Q38 shared-MTP support is absent from its `src/models/qwen4exp.cpp`**, so keep this upstream target-only; use the separate danielhanchen dependency guide for MTP. |
| DeepSeek-V4-Flash-0731 | `./build/bin/llama-server -m <DV4.gguf> -a dv4 -ngl auto --fit on -c 8192 -np 1 -fa on -ctk q8_0 -ctv q8_0 --host 127.0.0.1 --port <PORT>` | `deepseek4` exists. A DSpark speculative arm needs separate draft artifact, validated flag set and output/acceptance proof; do not blend it with target-only speed. |

If `--fit on` chooses full VRAM residency, also run a host-expert matched baseline using `--cpu-moe` (same model, context, KV and GPU) when comparing a cache that only acts on CPU experts. On multi-GPU, start with `-sm layer`; record `-ts` and `-mg` only after checking fit and chosen placements. For all models, verify outputs, model logs, memory fit and `llama-server --help` first. OOM, page faults and early EOS require an explicit failed/incomplete record.

## Two required measurements per model

**Coherent text:** With the relevant server above, save the complete response and log, including reasoning fields. Substitute `q36`, `q38` or `dv4` for the model alias, and perform a second longer request to prove sustained decode. Apply the runbook's minimal output sanity gate; assess whether the code and explanation complete the task separately.

```sh
curl -fsS http://127.0.0.1:<PORT>/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"<ALIAS>","messages":[{"role":"user","content":"Explain how a ring buffer handles wraparound, then provide a short C++ example."}],"temperature":0,"max_tokens":512,"stream":false}' \
  > <RUN_DIR>/coherence.json
```

**llama-benchy:** Use the same server, with a tokenizer matching the *actual* GGUF. The [vendored tool's documentation](https://github.com/eugr/llama-benchy#usage) describes `--model`, `--served-model-name`, `--tokenizer`, `--pp`, `--tg`, repeats and warmups. Preserve raw JSON and the tool revision. Inspect actual generated lengths, including any early EOS; do not assume the requested length was produced. `--exact-tg` requires the server to honor `min_tokens` and `ignore_eos`, so leave it off until validated.

```sh
llama-benchy --base-url http://127.0.0.1:<PORT>/v1 \
  --model <HF_TOKENIZER_ID> --served-model-name <ALIAS> --tokenizer <HF_TOKENIZER_ID_OR_LOCAL_PATH> \
  --pp 2048 --tg 128 512 --concurrency 1 --runs 3 --warmup-runs 1 \
  --latency-mode generation --format json --save-result <RUN_DIR>/benchy.json
```

Do not merge `Q36`, `Q38` or `DV4` output into one headline. Every model and placement arm needs its own coherent request, benchy artifact, prompt/output counts, TTFT, prompt rate, decode rate and memory record.
