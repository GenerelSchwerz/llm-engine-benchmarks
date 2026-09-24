# danielhanchen Qwen3.8 MTP dependency branch

Source: [`danielhanchen/llama.cpp:qwen4exp/mtp`](https://github.com/danielhanchen/llama.cpp/tree/qwen4exp/mtp), reviewed commit [`6fcaa16f4b360649933a54d1f91ad40ed35c0e11`](https://github.com/danielhanchen/llama.cpp/tree/6fcaa16f4b360649933a54d1f91ad40ed35c0e11), proposed as [upstream PR #28243](https://github.com/ggml-org/llama.cpp/pull/28243). Status: **source-reviewed research draft**; no build, binary help capture or model run here. This branch provides shared-head Qwen3.8 MTP compatibility. It is a **dependency/control branch, not an MoE expert-cache competitor**. When another fork needs this base, record base SHA and every applied cache patch as a separate tree and retain a target-only and MTP control on the same base.

## Source and build

[`src/models/qwen4exp.cpp`](https://github.com/danielhanchen/llama.cpp/blob/6fcaa16f4b360649933a54d1f91ad40ed35c0e11/src/models/qwen4exp.cpp) contains Q38 shared-target-tensor and MTP graph handling. The pinned [`common/arg.cpp`](https://github.com/danielhanchen/llama.cpp/blob/6fcaa16f4b360649933a54d1f91ad40ed35c0e11/common/arg.cpp) parses `-md`/`--spec-draft-model`, `--spec-type`, `--spec-draft-n-max`, `--fit-target`, KV types and `--no-kv-unified`. The PR says shared MTP modules reuse target embedding tensors and discusses draft fit/VRAM issues. Do not assume every MTP sidecar encoding is compatible; use the exact documented GGUF pair and hash both files.

CUDA build candidate: `cmake -S . -B build -DGGML_CUDA=ON && cmake --build build -j`; then save `build/bin/llama-server --help` and hashes. This source also contains `qwen35moe` and `deepseek4`, but its special value in this matrix is Q38 MTP. For non-Q38 target-only rows, use the separately pinned upstream baseline unless a cache fork's dependency chain makes this particular base necessary.

## Model commands

| Model | Research command / boundary |
| --- | --- |
| Qwen3.6-35B-A3B | No special Q36 feature is claimed by this PR. If required as a same-base control, run `./build/bin/llama-server -m <Q36.gguf> -a q36 -ngl auto --fit on -c 8192 -np 1 -fa on -ctk q8_0 -ctv q8_0 --host 127.0.0.1 --port <PORT>` after a successful load; otherwise use `upstream.md`. |
| Qwen3.8-Flash-Next target only | `./build/bin/llama-server -m <Q38.gguf> -a q38 -ngl auto --fit on -c 8192 -np 1 -fa on -ctk q8_0 -ctv q8_0 --host 127.0.0.1 --port <PORT>`; this is the matching no-MTP control. |
| Qwen3.8-Flash-Next + shared MTP | Same target command with `-md <Q38-shared-MTP.gguf> --spec-type draft-mtp --spec-draft-n-max 2`. Reserve draft memory using an independently checked `--fit-target` value if auto fit OOMs; do not copy another machine's MiB setting. Verify draft load, accepted lengths and final output. |
| DeepSeek-V4-Flash-0731 | `./build/bin/llama-server -m <DV4.gguf> -a dv4 -ngl auto --fit on -c 8192 -np 1 -fa on -ctk q8_0 -ctv q8_0 --host 127.0.0.1 --port <PORT>` is a same-base control only. No special DV4 feature is claimed by this PR. Validate load; otherwise use `upstream.md`. DSpark is a separate speculative feature and not this Q38 MTP implementation. |

Do not add `--no-kv-unified`, draft KV types or a forced draft GPU merely because another benchmark used them. Check exact revision help and model-specific load diagnostics; vary each as its own controlled arm. One public [reconstruction report](https://github.com/ggml-org/llama.cpp/discussions/24528) used an earlier PR base plus csantiago78 cache changes and follow-up patches. Those throughput results are **not** from this dependency branch alone, and the unpatched cache PR could not load the shared head. The branch here is at a later SHA than that report; validate it independently.

## Two required measurements

Use `-a q38` and the **same** GGUF, context, KV type, prompt and output limit for target-only and Q38 MTP. Save complete logs and check draft acceptance; a short successful launch is insufficient.

**Coherent text:**

```sh
curl -fsS http://127.0.0.1:<PORT>/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"q38","messages":[{"role":"user","content":"Explain how a ring buffer handles wraparound, then provide a short C++ example."}],"temperature":0,"max_tokens":512,"stream":false}' \
  > <RUN_DIR>/coherence.json
```

Inspect the full answer for coherence and completion. Run a longer shared prompt too, and report total generated tokens, end state and MTP acceptance. For Q36/DV4 same-base controls, replace `q38` with the corresponding alias.

**llama-benchy:** Use the [vendored tool](https://github.com/eugr/llama-benchy#usage) against the same local server. The served alias is distinct from the tokenizer ID. Record the raw result plus full server logs. Since speculative acceptance can vary by prompt, use matching warmups and repeat count and show acceptance alongside throughput.

```sh
llama-benchy --base-url http://127.0.0.1:<PORT>/v1 \
  --model <Q38_HF_TOKENIZER_ID> --served-model-name q38 --tokenizer <Q38_HF_TOKENIZER_ID_OR_LOCAL_PATH> \
  --pp 2048 --tg 128 512 --concurrency 1 --runs 3 --warmup-runs 1 \
  --latency-mode generation --format json --save-result <RUN_DIR>/benchy.json
```

Confirm actual output lengths. `--exact-tg` sends `min_tokens` and `ignore_eos`; do not use it until this binary is proven to honor both. Record command, code SHA, draft/target GGUF hashes, sidecar load state, VRAM, generated length and acceptance for every arm.
