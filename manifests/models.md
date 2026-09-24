# Model setups

Use the **Models** tab in `uv run scripts/tui.py`. Agent mode accepts a plain-language request such as “install Qwen 35B Q4_K_M and Qwen 27B from my local system.” The agent must either save the discovered setups and mark the request ready for confirmation, or return specific questions. Toggle off Agent mode to enter a path, URL, or service ID manually. A name is optional; the TUI generates an internal ID. Family, context length, compatible engine IDs, and notes are optional hints.

Setups live in the ignored local `benchmark-catalog.sqlite3`. The first launch imports an older `manifests/models.json` and `.benchmark-tui.json` if present, leaving those files in place as backups.

The preparation agent identifies exact revisions, tokenizer, quantization, and runtime compatibility. `uv run scripts/suite_store.py record-model SUITE MODEL_ID --revision REVISION --tokenizer TOKENIZER` hashes a local file or directory automatically; remote artifacts require a revision. The agent records model-specific commands with `record-packet` and freezes only after `validate` succeeds. Missing hashes, revisions, tokenizers needed by llama-benchy, or command packets cause an explicit error.
