# Fork source inventory

Snapshot: 2026-09-24. The source is [llama.cpp discussion #24528](https://github.com/ggml-org/llama.cpp/discussions/24528), including all 41 top-level comments and 65 replies visible through the GitHub API at inventory time. The editable install list is [`sources.json`](sources.json); keep its pins and this annotated table aligned. Local `sources/` checkouts are ignored by Git. No builds or benchmarks are implied by inclusion here.

| ID / local source | Repository and tracking branch | Pinned `HEAD` | Relationship / benchmark role | Discussion source | Availability |
|---|---|---|---|---|---|
| `upstream` | [`ggml-org/llama.cpp:master`](https://github.com/ggml-org/llama.cpp/tree/master) | `84e76d8a23162eca70490da131945ebec1f09bf4` | Baseline, upstream | [RFC](https://github.com/ggml-org/llama.cpp/discussions/24528) | Public, active |
| `leloch-v1` | [`leloch/llama.cpp:moe-cache-pr`](https://github.com/leloch/llama.cpp/tree/moe-cache-pr) | `a01eb26468a6cb2bf2c3bfd1cc3b5d9e64daefcd` | Upstream GitHub fork; original hybrid CPU/GPU hot-expert cache | [RFC](https://github.com/ggml-org/llama.cpp/discussions/24528) | Public, branch exists; superseded by v2 for current comparison |
| `leloch-v2` | [`leloch/llama.cpp:moe-cache-v2-pr`](https://github.com/leloch/llama.cpp/tree/moe-cache-v2-pr) | `e3096b046bb809f7f80bc47801f6579aed1cbc60` | Same fork; revised hybrid cache | [v2 announcement](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-17925743) | Public, active |
| `lidenburg` | [`Lidenburg/llama.cpp:moe-expert-caching`](https://github.com/Lidenburg/llama.cpp/tree/moe-expert-caching) | `e85e4d90cd44a8c8332093b0c97a53fa13137f5e` | Upstream GitHub fork; GPU execution and expert cache | [author's post](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-17297984) | Public, branch exists; Windows build concerns reported in discussion |
| `generelschwerz` | [`GenerelSchwerz/llama.cpp:moe-cache`](https://github.com/GenerelSchwerz/llama.cpp/tree/moe-cache) | `e59a4b14ca9d681b7631d0d729baf95d1e2a3701` | Upstream GitHub fork; grouped GPU decode with expert cache | [introduction](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18373410) | Public, active |
| `thecodacus` | [`thecodacus/llama.cpp:perf`](https://github.com/thecodacus/llama.cpp/tree/perf) | `27c54b4bbcefadedcec6397477cc2e866c1db716` | Upstream GitHub fork; expert cache, async prefetch, pinned host memory; `perf` is default branch and README documents these together | [comparison](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18531512) | Public, active |
| `thetom` | [`TheTom/llama-cpp-turboquant:feature/turboquant-kv-cache`](https://github.com/TheTom/llama-cpp-turboquant/tree/feature/turboquant-kv-cache) | `a3d5603d110bda29222d2011596cdc84d7fa532d` | Upstream GitHub fork; expert cache plus TurboQuant KV path | [tested branch](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18259037) | Public, active |
| `giveen-current` | [`giveen/llama-cpp-turboquant:feature/turboquant-kv-cache`](https://github.com/giveen/llama-cpp-turboquant/tree/feature/turboquant-kv-cache) | `bcc337d69f4065cb37f2aa5bd17c34fed87bd6f4` | GitHub fork of TheTom's repository; current cache-capable source (`common/fit.cpp` and CUDA cache code verified), distinct from the missing historical `moe-cache` branch | [author's original branch mention](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-17969364) | Public, active; current checkout is **not** the historical discussion snapshot |
| `miltos22` | [`miltos22/llama.cpp-wackMall-merge-request:master`](https://github.com/miltos22/llama.cpp-wackMall-merge-request/tree/master) | `6cacc5edbb2e265133491f0e4a5ba9a470f771a2` | Upstream GitHub fork; alternate MoE execution/cache | [cross-fork comparison](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-17938278) | Public, active |
| `atomic-germ` | [`Atomic-Germ/llama.cpp:feat/qwen38-moe-gpu-pill-streaming`](https://github.com/Atomic-Germ/llama.cpp/tree/feat/qwen38-moe-gpu-pill-streaming) | `cd252aa7e0e01d74647eeaa3c9634ff23979ea06` | Upstream GitHub fork; UMA, Vulkan/HIP-specific streaming | [author's post](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18532761) | Public, active; requires compatible UMA hardware |
| `mclaudod` | [`mclaudod/llama.cpp:moe-hot-cache`](https://github.com/mclaudod/llama.cpp/tree/moe-hot-cache) | `b5516876f10c7ceea1ba4695cdcdc80f71c71c5f` | Upstream GitHub fork; hot-cache implementation | [author's post](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18140286) | Public, active; user reports of OOM in discussion need validation |
| `freetoken` | [`FlashML-org/FreeToken:main`](https://github.com/FlashML-org/FreeToken/tree/main) | `cee23bf44a86e48d70f8fda3ca3b6d4d9890072e` | Independent inference engine, not a GitHub fork of llama.cpp; GPU, CPU, and hybrid MoE strategies | [comparison mention](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18529416) | Public, active |
| `ktransformers` | [`kvcache-ai/ktransformers:main`](https://github.com/kvcache-ai/ktransformers/tree/main) | `c40722bf04c494f2492b7eb9e86ef01a4ede45b3` | Independent heterogeneous inference runtime; historically used expert caching, but not an active llama.cpp fork arm | [runtime mention](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18369105) | Public, active; benchmark eligibility requires a separate model/backend guide |
| `buun` | [`spiritbuun/buun-llama-cpp:master`](https://github.com/spiritbuun/buun-llama-cpp/tree/master) | `2ef0317dd91e2ca4732fffa456dc5e2311db41c7` | Independent GitHub repository derived from llama.cpp; [README documents MoE cache](https://github.com/spiritbuun/buun-llama-cpp/blob/master/README.md#deepseek-v4-flash-and-qwen38-flash-next--moe-cache) | [User addition](https://github.com/spiritbuun/buun-llama-cpp) | Public, active; not named in #24528 |
| `csantiago78` | [`csantiago78/llama.cpp:moe-expert-cache`](https://github.com/csantiago78/llama.cpp/tree/moe-expert-cache) | `bccbacdb8945680f1cfc7e6bffd1e59014705750` | Upstream GitHub fork; expert-cache [PR #27861](https://github.com/ggml-org/llama.cpp/pull/27861) | [discussion comparison](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18546706) | Public branch and PR; reported fastest patched test tree is not this public commit |
| `danielhanchen-mtp` | [`danielhanchen/llama.cpp:qwen4exp/mtp`](https://github.com/danielhanchen/llama.cpp/tree/qwen4exp/mtp) | `6fcaa16f4b360649933a54d1f91ad40ed35c0e11` | Upstream GitHub fork; shared-MTP base dependency for the public csantiago78 reconstruction, **not** a separate expert-cache benchmark arm | [reconstruction notes](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18548500), [PR #28243](https://github.com/ggml-org/llama.cpp/pull/28243) | Public, active; discussion reconstruction used older `53b1389d0bf98fa367e2a0ce0475008e762ebf28`, so current head is not that exact base |
| `guanaco` | [`Atomic-Germ/Guanaco:main`](https://github.com/Atomic-Germ/Guanaco/tree/main) | `8364229686d74ec7495d2e726268bb329e759e84` | Independent companion/patch project with llama.cpp submodule; not a standalone llama.cpp benchmark arm | [author's post](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18006845) | Public; submodules intentionally not fetched |

## Mentioned variants without a reproducible public branch

| Variant | Status | Source |
|---|---|---|
| `giveen/llama-cpp-turboquant:moe-cache` | [The named historical branch](https://github.com/giveen/llama-cpp-turboquant/tree/moe-cache) no longer resolves via GitHub API; [PR #340](https://github.com/TheTom/llama-cpp-turboquant/pull/340) is closed and its `qwen4-catchup` source branch is also absent. A **different, current cache-capable branch** is collected as `giveen-current`. | [giveen's post](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-17969364) |
| `SharkWipf` cache implementation | Author explicitly says the implementation is [not published](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18253201). No source to pin. | [author's post](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18253201) |
| `Volunteer-1` patched cross-fork binaries, including csantiago78 | Discussion describes local cherry-picks and fixes. The exact tested trees are not public, so the published fork heads above are **different** source snapshots. | [cross-fork matrix](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18531512), [csantiago comparison](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-18546706) |
| `Crow` disk-backed streaming | The discussion gives measurements and command flags but no public fork URL or patch sufficient to reconstruct it. | [author's post](https://github.com/ggml-org/llama.cpp/discussions/24528#discussioncomment-17978601) |

The discussion also links to unrelated driver, infrastructure, model, issue, and upstream-PR repositories. They are not inference-engine fork arms. Guanaco is retained above because its llama.cpp patch/submodule is directly discussed, but it requires a separate setup and benchmark contract.

## Repeatable source updates

Each row gives the **tracking branch** and the **pinned SHA**. Before any run, check that the checkout still equals its manifest pin:

```sh
git -C sources/<id> rev-parse HEAD
git -C sources/<id> status --short
```

To check whether a public branch has moved without changing the checkout, use the repository and branch from the table:

```sh
git ls-remote https://github.com/<owner>/<repo>.git refs/heads/<tracking-branch>
```

The output is empty if the branch is missing or retired. An update is a **new benchmark suite revision**, never an action during a run. After stopping all runs and saving their manifests/results, fetch a chosen branch and detach at its new head, then update its pinned SHA in this table and regenerate affected commands/guides:

```sh
git -C sources/<id> fetch --depth 1 origin refs/heads/<tracking-branch>
git -C sources/<id> switch --detach FETCH_HEAD
git -C sources/<id> rev-parse HEAD
```

Use a single manifest revision across compared arms. Do not assume that current branch heads recreate discussion measurements, which used older commits, local patches, different models, and distinct hardware.
