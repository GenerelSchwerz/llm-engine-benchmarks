# GenerelSchwerz llama.cpp `moe-cache`

Source: [GenerelSchwerz/llama.cpp `moe-cache`](https://github.com/GenerelSchwerz/llama.cpp/tree/moe-cache)
Reviewed revision: [`e59a4b14ca9d681b7631d0d729baf95d1e2a3701`](https://github.com/GenerelSchwerz/llama.cpp/tree/e59a4b14ca9d681b7631d0d729baf95d1e2a3701) (pin again before benchmarking)
Guide status: source-reviewed research draft; the new templates below have not had a build, `--help`, coherent model run, or throughput run in this workspace. The historical wiki commands retain their own separate provenance.

The MoE cache requires CUDA. Use `--load-mode none` when the cold expert source fits system RAM. Keep cache slots, KV, workspace, draft model, and host-pinning budgets separate. Confirm grouped/cache counters after generation, since an allocated cache alone does not prove the intended path executed. [Flags and setup](https://github.com/GenerelSchwerz/llama.cpp/wiki/MoE-Cache-Flags-and-16GB-Setup).

## Current-source controls and model eligibility

The pinned [argument parser](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/common/arg.cpp) defines `--moe-expert-cache-size N` as slots **per expert tensor** on the owning CUDA device; `0` disables the cache. `--moe-expert-cache-mib MiB[,MiB,...]` instead derives owner-local slots from a per-device byte budget and conflicts with a nonzero slot count. A positive `--moe-expert-cache-host-pinned-mb N` bounds model-wide source registration and staging, whereas `0` first attempts full pinning. Slot count, VRAM, pinned RAM, and pageable backing are distinct quantities. A cache-enabled loader claims matched routed expert tensors even when `--cpu-moe` is present, unless an explicit cache-layer selector changes placement precedence. The [fork feature guide at this revision](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/docs/fork-features.md) details these rules; the [model constructor](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/src/llama-model.cpp) rejects a simultaneous byte budget and positive slot count.

| Model | Source-level evidence | Qualification boundary |
| --- | --- | --- |
| Qwen3.6-35B-A3B | `qwen35moe` is mapped in [`llama-arch.cpp`](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/src/llama-arch.cpp); [Qwen3.5-MoE model code](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/src/models/qwen35moe.cpp) includes a one-block MTP graph. | Historical Qwen3.6 artifacts below are from older commits. Recheck this GGUF's architecture/quant, output, and cache telemetry at the reviewed revision. |
| Qwen3.8 Flash Next | `qwen4exp` is mapped in [`llama-arch.cpp`](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/src/llama-arch.cpp); [Qwen4Exp model code](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/src/models/qwen4exp.cpp) includes a one-block MTP graph. | Confirm the GGUF actually declares `qwen4exp` and contains routed experts. The separate Qwen3.8-27B dense model is not a MoE-cache case. |
| DeepSeek V4 Flash | `deepseek4` target and `dflash` draft mappings are in [`llama-model.cpp`](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/src/llama-model.cpp); [DeepSeek4 model code](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/src/models/deepseek4.cpp) has a one-block MTP path, while [`dflash.cpp`](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/src/models/dflash.cpp) includes DSpark-draft metadata. | Architecture parsing is present, but this guide has no owner-verified DeepSeek V4 completion or cache benchmark at the reviewed revision. Target-only, MTP, and DSpark need separate qualification. |

Use layer split for a multi-GPU cache run. [Model creation](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/src/llama-model.cpp) rejects tensor split with a nonzero cache, and the [fork feature guide](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/docs/fork-features.md) says row/tensor sharding of cached experts is not implemented. `--moe-early-router`, backend sampling, decode overlap, and workspace resizing are independent opt-ins; add one at a time after the basic cache path is proven. The [parser](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/common/arg.cpp) describes `--ple-prefetch` as Linux-oriented and Windows-unvalidated. `--spec-draft-ubatch-size` caps the **physical draft microbatch** and does not replace target `-ub`. The cache [feature guide](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/docs/fork-features.md) says MTP with no separate draft file shares target weights and target cache controls; a separately loaded draft has independent cache options and memory.

## Qwen3.6 35B A3B, Q8-dense/NVFP4-expert GGUF

The [September 23 comparison](https://github.com/GenerelSchwerz/llama.cpp/wiki/FreeToken-vs-MoE-Cache-Qwen3.6-2026-09-23) pinned a GGUF with SHA256 `0d223b5b85f5970216ce7d9f622a8b916f0de415e190cb489acbb3035a36bf62` and an MTP sidecar with SHA256 `606fca331adcbfbdadc107512ce6a7161e84e1646ba0e0018256426f6296877f`. Its measured fork commit was `b6933a2ca754b6456da3eb6fd13e01d0e67e59b7`. Revalidate all flags on the new pinned snapshot.

Historical cache-enabled, no-MTP command:

```sh
CUDA_VISIBLE_DEVICES=0 LD_LIBRARY_PATH="$(dirname "$FORK_BIN")" "$FORK_BIN" \
  --model "$QWEN36_GGUF" --host 127.0.0.1 --port "$PORT" \
  -c 65536 -b 8192 -ub 4096 -np 1 -ctk f16 -ctv f16 -kvo \
  --load-mode none --no-warmup -fa on -ngl all -fit off \
  --moe-expert-cache-size 128 --cache-ram 0 --no-cache-prompt \
  --no-phase-aware-workspace --skip-chat-parsing --spec-type none \
  --backend-sampling --experimental-logs -n 1024 --log-colors off \
  --decode-overlap -ot token_embd.weight=CUDA0 -v
```

Historical matched MTP control used `-ub 1024`, `--decode-boundary-overlap`, and `--moe-early-router` in **both** MTP and no-MTP legs. Add `-md "$QWEN36_MTP" -ngld all --spec-type draft-mtp --spec-draft-n-max 2 --spec-draft-p-min 0` only for MTP-2. These are not a one-flag A/B against the command above; use the exact matched family in the cited page. Cache-off placement and output-oracle controls still need to be defined for the new sweep.

## Qwen3.8 Flash Next, UD-Q3_K_XL GGUF

The [notable runs](https://github.com/GenerelSchwerz/llama.cpp/wiki/Notable-Runs) used `moe-cache` commit `925933801` on an RTX 5070 Ti. The command below is its historical MTP-2/full-pin configuration, with workspace model paths substituted. The chosen GGUF and sidecar hashes must be recorded before reuse.

```sh
CUDA_VISIBLE_DEVICES=0 LD_LIBRARY_PATH="$(dirname "$FORK_BIN")" "$FORK_BIN" \
  --offline --model "$QWEN38_GGUF" -md "$QWEN38_MTP" \
  --spec-type draft-mtp --spec-draft-n-max 2 \
  -c 65536 -b 512 -ub 512 -np 1 -ngl all -fa on -fit off \
  --load-mode none --lazy-mode on \
  --moe-expert-cache-size 56 --moe-early-router \
  -ctk f16 -ctv f16 -kvo --cache-ram 0 --jinja --no-warmup \
  --backend-sampling --decode-overlap --decode-boundary-overlap \
  --ple-prefetch --phase-aware-workspace --live-context-workspace \
  --experimental-logs -n 1024 --host 127.0.0.1 --port "$PORT"
```

The historical no-MTP run used `-b 4096 -ub 512`, Q8 KV, 80 cache slots, and no sidecar. That is a different memory and execution envelope, so it needs a new matched control. Verify coherent output, final grouped telemetry, MTP acceptance, peak VRAM, and sustained delivery.

## DeepSeek V4 Flash

No owner-verified DeepSeek V4 launch command was found in this fork's current public benchmark wiki. Mark this pair `not yet qualified` until the pinned binary's `--help`, model/draft compatibility, and a coherent completion are captured. Do not adapt another fork's DSpark command silently.

## Additional sweep models

Gemma 4, Nemotron, GPT-OSS, LFM2.5, and Ornith have historical model-specific commands in the [benchmark index](https://github.com/GenerelSchwerz/llama.cpp/wiki/Benchmark-Comparison-Showcase) and linked reports. Copy them only after pinning exact current model artifacts and checking the new binary's CLI. Include the published regressions and LFM grouped-certificate failure as explicit controls.

## New sweep: target-only research templates

These commands are **not measured optima**. They establish the minimum target-only cache arm at the pinned source revision, before separately testing overlap, early routing, prompt-workspace policy, or MTP. Build the pinned revision with CUDA, run `"$FORK_BIN" --help`, hash every GGUF, and confirm its metadata, supported quant, and chat template. Set `PORT`, `THREADS`, `CTX`, and the model path for each host; `CTX=8192` is a reasonable short-context qualification point, not a long-context claim. `--load-mode none --lazy-mode off` assumes the cold expert source fits RAM and avoids page faults; with a smaller RAM budget, test `--load-mode mmap --lazy-mode on` as a distinct configuration and record disk stalls. The [parser](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/common/arg.cpp) states lazy reading requires mmap. Hold flash attention and F16 KV fixed initially; sweep KV quant and context afterward with output-quality checks.

Qwen3.6, no MTP: `Q36_SLOTS` is a per-tensor slot count. Start with a value that fits, then sweep it while recording actual cache allocation, hits, grouped completions, and peak VRAM. The historical 128-slot run above is evidence for its *old* hardware/artifact/revision, not a universal setting. Source: [cache controls](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/common/arg.cpp), [allocation rules](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/docs/fork-features.md).

```sh
"$FORK_BIN" -m "$QWEN36_GGUF" -a q36 --host 127.0.0.1 --port "$PORT" \
  -c "$CTX" -np 1 -ngl all -fit off --jinja -fa on \
  -ctk f16 -ctv f16 --load-mode none --lazy-mode off \
  --moe-expert-cache-size "$Q36_SLOTS" --spec-type none \
  -t "$THREADS" --experimental-logs -lv 4
```

Qwen3.8 Flash Next, no MTP: start from the historical 56-slot observation only if the same UD-Q3_K_XL GGUF, GPU, and memory envelope are retained; otherwise treat `Q38_SLOTS` as a fresh sweep variable. Keep the initial arm target-only to separate cache throughput from MTP acceptance. The historical `--load-mode none --lazy-mode on` pairing above should be rechecked against current parser semantics; this template deliberately uses `lazy-mode off` with `none`. Confirm that the model is routed `qwen4exp` in metadata. Source: [model code](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/src/models/qwen4exp.cpp), [load/lazy parser](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/common/arg.cpp).

```sh
"$FORK_BIN" -m "$QWEN38_GGUF" -a q38 --host 127.0.0.1 --port "$PORT" \
  -c "$CTX" -np 1 -ngl all -fit off --jinja -fa on \
  -ctk f16 -ctv f16 --load-mode none --lazy-mode off \
  --moe-expert-cache-size "$Q38_SLOTS" --spec-type none \
  -t "$THREADS" --experimental-logs -lv 4
```

DeepSeek V4 Flash, no MTP or DSpark: this is an **unqualified candidate**. `DSV4_CACHE_MIB` is a per-device MiB budget, chosen only after inspecting model size and free VRAM. Byte-budget mode is useful here because the source derives a slot count from actual expert tensor strides and reserves; it cannot be combined with `--moe-expert-cache-size`. Confirm the GGUF reports a routed `deepseek4` target, the cache allocates nonzero slots, and generation completes coherently. A DFlash/DSpark file belongs to the *draft* arm, not this target model path. Source: [budget parser](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/common/arg.cpp), [model constructor](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/src/llama-model.cpp), [DSpark description](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/docs/speculative.md).

```sh
"$FORK_BIN" -m "$DSV4_GGUF" -a dsv4 --host 127.0.0.1 --port "$PORT" \
  -c "$CTX" -np 1 -ngl all -fit off --jinja -fa on \
  -ctk f16 -ctv f16 --load-mode none --lazy-mode off \
  --moe-expert-cache-mib "$DSV4_CACHE_MIB" --spec-type none \
  -t "$THREADS" --experimental-logs -lv 4
```

If `-ngl all` plus the chosen cache cannot fit dense layers, KV, workspace, and slots, reduce context or cache capacity before moving dense layers to CPU; record any placement change as another arm. On a multi-GPU host, choose layer split and a device-order-aware budget. For a cache-off control, set slot count to `0` and omit byte-budget mode; confirm placement and output because cache enablement changes routed-expert placement. For a memory-controlled host-pinning sweep, add a positive `--moe-expert-cache-host-pinned-mb N`, verify that mandatory staging fits, and log pageable fallback. Use `--moe-early-router` only in a separately measured arm. Source: [feature rules](https://github.com/GenerelSchwerz/llama.cpp/blob/e59a4b14ca9d681b7631d0d729baf95d1e2a3701/docs/fork-features.md).

## Two measurements for each qualified model

1. **Coherent-text server run.** Start a fresh server with one of the target-only commands. Substitute its alias `q36`, `q38`, or `dsv4` in the request. Preserve visible and reasoning text, finish reason, token count, timing, process logs, and actual GPU/RAM usage. Apply the runbook's minimal output sanity gate, report answer completeness and correctness separately, and check final cache/grouped telemetry for the intended path. An architecture appearing in source, a successful load, or a first token is insufficient.

   ```sh
   curl -fsS "http://127.0.0.1:$PORT/v1/chat/completions" \
     -H 'Content-Type: application/json' \
     -d '{"model":"q36","messages":[{"role":"user","content":"Write a short Python function to merge sorted lists, then explain its complexity."}],"temperature":0,"max_tokens":512}'
   ```

2. **`llama-benchy` server run.** Set `TOKENIZER` to the exact tokenizer matching the GGUF and `ALIAS` to `q36`, `q38`, or `dsv4`; run once per supported model. The vendored [benchy documentation](https://github.com/eugr/llama-benchy#usage) defines these options and runs a coherence check by default. Confirm the installed `--help` and OpenAI-compatible endpoint on this binary. The depth test must fit `CTX` including prompt and generation; increase `CTX` before adding longer depths.

   ```sh
   uv run --project tools/llama-benchy llama-benchy \
     --base-url "http://127.0.0.1:$PORT/v1" \
     --model "$TOKENIZER" --served-model-name "$ALIAS" \
     --pp 2048 --tg 512 --depth 0 4096 --runs 3 --warmup-runs 2 \
     --latency-mode generation --concurrency 1 --format json \
     --save-result "$RESULT_JSON"
   ```

For every row, record full fork SHA, GGUF/sidecar SHA256, quant, tokenizer, CUDA/driver, GPU and RAM, host-pinning limit, load mode, context, KV, slots or MiB budget, actual cache residency and grouped completion counters, TTFT, prefill, decode, output coherence, and peak VRAM/RSS. Then add **separate** matched Qwen MTP-2, DeepSeek MTP, and DSpark arms only after target-only results pass. MTP tests must include acceptance and target/draft physical ubatch, and preserve the historical comparison's matched controls. Never infer cache efficacy from `-ngl all` or an allocated pool alone. No new benchmark result is claimed here.
