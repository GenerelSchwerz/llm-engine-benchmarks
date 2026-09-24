# Model setups

Use the **Models** tab in the TUI to create or edit `manifests/models.json`. That file is local and ignored by Git because artifact paths and service IDs may be machine-specific. The TUI saves selections in an ignored `.benchmark-tui.json`; the agent freezes exact model details for each suite under `manifests/suites/<suite-id>/`.

A setup identifies one exact artifact or service model. Use separate entries for GGUF and native checkpoints, quantizations, or draft variants. Enter an artifact path, URL, or service model ID; its revision, tokenizer, quantization/dtype, context length, optional SHA256 and draft artifact, and applicable engine IDs. An empty applicable-engine list means the setup is available to any selected engine, subject to a later compatibility check.

The checked-in [empty example](models.example.json) shows the file shape. If editing JSON directly, use:

```json
{
  "schema_version": 1,
  "models": [
    {
      "id": "example-q4",
      "family": "ExampleModel",
      "artifact": "/models/example-q4.gguf",
      "revision": "release-1",
      "sha256": "",
      "tokenizer": "example/tokenizer",
      "quant_or_dtype": "Q4",
      "context": 8192,
      "draft_artifact": "",
      "engine_ids": ["upstream"],
      "notes": ""
    }
  ]
}
```

The TUI validates IDs, engine references, context length, and any supplied SHA256 before saving. A model setup is input metadata, not proof that an engine supports or runs the artifact.
