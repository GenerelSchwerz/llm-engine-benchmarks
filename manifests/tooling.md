# Tooling snapshot

| Tool | Source | Pinned revision | Role |
| --- | --- | --- | --- |
| llama-benchy | https://github.com/eugr/llama-benchy | `e9be344578cec17745066b220798b80a0d2686d3` | OpenAI-compatible endpoint benchmark |

The checkout is in `tools/llama-benchy`. Its [README](https://github.com/eugr/llama-benchy) documents `--pp`, `--tg`, `--depth`, `--runs`, `--concurrency`, `--tokenizer`, JSON output, and a built-in coherence probe. It only uses `/v1/chat/completions`. The built-in probe does not replace the separate coherent-text track in this suite.

Before a live run, install the pinned checkout in an isolated environment and capture `llama-benchy --help` and its tool version. Do not track a moving `main` or PyPI release during a sweep. Record the corpus URL, local cached corpus hash, tokenizer revision, and actual output token counts. Do not assume `--exact-tg` works on every server; check its `min_tokens` and `ignore_eos` behavior for each runtime first.

At this pinned revision, `src/llama_benchy/corpus.py` catches both tokenizer-loading failures and then **falls back to the GPT-2 tokenizer**. Before measuring, confirm the requested model tokenizer loaded successfully and abort that arm if the log says `Falling back to 'gpt2' tokenizer as approximation.` Otherwise the requested `--pp` and `--depth` no longer describe the model's token geometry. The book text is cached at `~/.cache/llama-benchy/<md5(book-url)>.txt`; freeze its SHA256 and verify the same bytes for each arm, even when the URL is unchanged.
