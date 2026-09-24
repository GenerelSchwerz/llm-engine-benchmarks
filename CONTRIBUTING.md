# Contributing

Engine additions, setup corrections, workload fixtures, and measured results are welcome. Engine checkouts, weights, builds, and raw captures stay outside Git.

1. Add an entry to `manifests/sources.json` with a unique ID, source type, and immutable revision or digest. Add context to `manifests/engines.md` when useful. Git sources can use `uv run scripts/install_sources.py --id ID`; other source types need reproducible `install_notes` and version verification.
2. Write a guide using `guides/TEMPLATE.md`. State how to install, launch, stop, and inspect the engine; map model artifacts and any endpoint aliases; give baseline and tuned commands per supported model. Provide evidence for engine-specific options and mark unrun commands as drafts.
3. Describe how the engine exposes OpenAI-compatible chat for llama-benchy, or document a protocol adapter. Record unsupported behavior instead of silently substituting another workload.
4. For measured results, follow `RUNBOOK.md`: pin artifacts, match controls, inspect full output, retain timings and memory evidence, and state limitations. Keep credentials and private captures out of Git.

The MIT license covers this repository's original scripts and documentation. Third-party engines and tools keep their own licenses.
