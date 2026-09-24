# Contributing

Fork additions, corrections, and measured results are welcome. This repository tracks instructions and public fixtures; backend checkouts, weights, builds, logs, and raw results stay out of Git.

To add or update a runtime:

1. Edit `manifests/sources.json` with its public repository, tracking branch, exact commit, unique ID, and `backend` kind. Update `manifests/forks.md` with its relationship to the other implementations and source evidence.
2. Add or update its guide under `guides/`. Include model-specific baseline and tuned commands, build requirements, supported and unsupported models, source references for flags, and both coherent-text and llama-benchy methods. Mark unrun commands as research drafts.
3. Run `python scripts/install_sources.py --id ID` and `python scripts/check_sources.py --remote` to confirm the pin is fetchable and local source is clean. Review the exact binary's help and run a model before calling any command validated.
4. For benchmark submissions, follow `RUNBOOK.md` and include pinned artifacts, matched controls, complete output, memory and timing evidence, and limitations. Avoid publishing private prompts, credentials, or raw logs that contain private data.

The MIT license covers this repository's original scripts and documentation. Cloned runtimes and llama-benchy retain their own licenses and are not included here.
