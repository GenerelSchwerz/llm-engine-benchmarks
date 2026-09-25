# Engine name

Source type and URL:
Pinned revision, image digest, or service version:
Guide status: research draft | CLI verified | model-run verified

## Install and verify

Give exact, reproducible install/build instructions for this engine. Record runtime dependencies, backend/driver requirements, version command, executable or image digest, and any required credentials by name only. Do not publish secrets.

## Launch, API, and teardown

Provide baseline and tuned launch commands, effective endpoint or CLI invocation, health/model-discovery checks, served model alias, and clean shutdown steps. If the engine is a remote service, record API version, region, service model ID, and relevant rate limits. Describe an OpenAI-compatible chat endpoint or the adapter needed for llama-benchy.

## Models in this suite

For **each** supported model, record:

- Exact artifact, revision/hash, tokenizer, format, quantization or dtype, and context limit.
- Model support status and source or binary evidence.
- Baseline command and optimized command, including all environment settings.
- Why each optimization or nondefault option is used; expected proof counters, if any.
- Known failure modes and validation status.

Mark unsupported models and modes explicitly. Do not copy a command from another engine without verifying this engine's parser, model loader, and runtime behavior.

## Both measurement methods

Describe a coherent generation request using the suite's frozen fixture and an independent llama-benchy command against the same engine/model configuration. If llama-benchy needs a protocol adapter, give its source/version and mapping. If the engine cannot be adapted faithfully, mark that method unavailable and explain why. Record actual output length and all visible and reasoning text for both methods. Use the [runbook's minimal output sanity gate](../RUNBOOK.md#method-a-coherent-generation); review task completion and correctness separately.
