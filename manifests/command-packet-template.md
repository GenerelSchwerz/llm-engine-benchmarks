# Fork/model command packet

One packet covers one fork, one exact model artifact, one hardware cohort, and one benchmark mode. Return a packet for unsupported pairs too.

- Suite ID and research agent:
- Fork ID, repository, tracking branch, previous validated SHA, observed remote SHA, frozen SHA:
- Source status: `reuse` / `review required` / `unavailable` / `unsupported`
- Model ID, quant, source revision, SHA256, tokenizer and draft hashes:
- Hardware/OS/backend cohort and memory ceiling:
- Prior validated command/result IDs, if reuse is claimed:
- Diff and source/arg-parser/build files inspected if changed:
- Build command and required runtime environment:
- Method A baseline server command and request fixture:
- Method A tuned server command and why each differing flag is used:
- Method B server command, served alias, tokenizer, and llama-benchy client command:
- Context capacity, batch/ubatch, parallel slots, load mode, KV types, cache budget, draft configuration:
- Expected proof counters and completion/quality gates:
- Known failures, unsupported features, and unresolved questions:
- Evidence URLs or local source file/line references:
- Validation status: source-reviewed / binary-help-checked / model-run-checked:

Do not label an updated fork's command "previously validated" until the new pinned binary and model run pass. Keep the previous command and result available for regression comparison.
