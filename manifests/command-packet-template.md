# Engine/model command packet

One packet covers one engine, exact model artifact, hardware cohort, and benchmark method. Return packets for unsupported or unavailable pairs too.

- Suite ID and research agent:
- Engine ID, source type, prior validated revision, observed revision, frozen revision/digest:
- Source status: `reuse` / `review required` / `unavailable` / `unsupported`:
- Model ID, format, quant/dtype, source revision, SHA256 or service ID, tokenizer/draft hashes:
- Hardware/OS/backend cohort and memory ceiling:
- Prior validated command/result IDs, if reuse is claimed:
- Source/API/default changes and evidence inspected:
- Install/build command and version verification:
- Method A baseline launch/invocation and frozen request fixture:
- Method A tuned launch/invocation and rationale for each changed setting:
- Method B endpoint, served alias, tokenizer, adapter/version if needed, and llama-benchy command; or unavailable reason:
- Context, batching, parallelism, placement, KV/cache/draft settings where applicable:
- Expected proof counters and output/quality gates:
- Known failures, unsupported features, unresolved questions:
- Evidence URLs or local source file/line references:
- Validation status: source-reviewed / engine-verified / model-run-checked:

A changed engine cannot inherit a "previously validated" label from an older revision. Keep the prior packet and result for regression comparison.
