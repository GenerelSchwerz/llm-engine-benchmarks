# Cross-fork benchmark workspace

- Read `RUNBOOK.md`, `manifests/forks.md`, `manifests/matrix.md`, and the exact fork guide before any build or run.
- Keep each fork's source, build, libraries, flags, result, and revision separate. Never build in `sources/` or overwrite a result.
- Use both methods in the runbook: coherent-text requests and pinned `llama-benchy`. Neither substitutes for the other.
- Follow each fork's model-specific guide; validate its command against the pinned source and binary before measuring.
- Never update a source checkout in the middle of a run or compare results from unrecorded commits.
- Preserve raw commands, prompts, outputs, server logs, benchmark JSON, memory samples, and errors. Report unavailable, failed, and slower cases.
- Publishing requires an explicit user instruction to publish the benchmark update. When authorized, re-fetch the wiki, edit relevant pages, push, and verify the rendered result.
