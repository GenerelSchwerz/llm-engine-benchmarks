# Coherent-generation fixtures

These are public, self-contained Method A prompts. Send exact bytes as the user message. Record SHA256, tokenizer/template, actual prompt tokens, request settings, and complete response. Keep task evaluation separate from speed measurement.

| Fixture | SHA256 | Minimum review criteria |
| --- | --- | --- |
| `coding-task.txt` | `f19b3e9a5343931262b7ca7830417f332de068e22d689d24b89428f7eb5cdd60` | Code meets the input/output contract, handles invalid input, and includes runnable tests. |
| `systems-task.txt` | `63be4fb3b7e0d026c481331cb20f796b6ad792bc57e65a3bd8e00b1b030aedac` | Explanation covers bounded capacity, retries, outcomes, failure cases, and queue versus processing measurements. |
| `moe-cache-task.txt` | `610df626726af5b8c223fc1e1fe609eeaed5d59de7ac4873b60d4b6b30581ef9` | Optional MoE-specific task; explanation preserves correct fallback and asynchronous safety. |

For long context, use a frozen public-domain document or synthetic dossier with a recorded hash and a task that requires information from both its beginning and end. Freeze it before measuring any engine.
