# Coherent-text fixtures

These are public, self-contained prompts for Method A in the top-level runbook. Send their exact bytes as the user message. Record SHA256, tokenizer/template, actual prompt tokens, request settings, and complete response. Keep task evaluation separate from speed measurement.

| Fixture | SHA256 | Minimum review criteria |
| --- | --- | --- |
| `coding-task.txt` | `f19b3e9a5343931262b7ca7830417f332de068e22d689d24b89428f7eb5cdd60` | Code meets the stated input/output contract, handles duplicate/invalid inputs, and includes runnable tests. |
| `systems-task.txt` | `610df626726af5b8c223fc1e1fe609eeaed5d59de7ac4873b60d4b6b30581ef9` | Explanation respects asynchronous completion, capacity, correctness fallback, and measurement limits. |

For a long-context coherent run, prepend a frozen, public-domain document or a synthetic repository dossier with a recorded hash and ask a task that requires information from both its beginning and end. Freeze that added fixture before measuring any runtime; do not generate a different document per fork.
