# Editable source manifest

`manifests/sources.json` has a `schema_version` and a `sources` array. Each entry has a unique filesystem-safe `id`, `kind` (`engine` or `tool`), and `source` object. Keep one exact, immutable version for each suite. The list is a starting point, not a fixed set of supported engines.

## Git checkout

```json
{"id":"example","kind":"engine","source":{"type":"git","url":"https://example.org/team/engine.git","ref":"main","revision":"<40-character commit SHA>"}}
```

The installer can fetch this type into ignored `sources/<id>` or `tools/<id>`. `ref` is the tracking branch; `revision` is the pinned commit. Update both deliberately and create a new suite revision after a source change.

## Other install types

For these, the installer prints `install_notes` and does not execute untrusted shell commands from the manifest. The engine guide gives exact installation and version-verification steps. The source checker reports `manual_verification_required` for each non-Git entry.

```json
{"id":"packaged-engine","kind":"engine","source":{"type":"package","manager":"pip","name":"example-engine","version":"1.2.3"},"install_notes":"Create an isolated environment; install example-engine==1.2.3; record the resolved wheel hash."}
```

```json
{"id":"container-engine","kind":"engine","source":{"type":"container","image":"registry.example/engine@sha256:<digest>"},"install_notes":"Pull the immutable image digest; record runtime and GPU settings."}
```

```json
{"id":"remote-engine","kind":"engine","source":{"type":"remote","provider":"Example","model":"model-id","version":"2026-09-24"},"install_notes":"Record endpoint, region, API version, and response metadata. Keep credentials outside the manifest."}
```

```json
{"id":"local-engine","kind":"engine","source":{"type":"local","path_hint":"/path/to/executable","sha256":"<file hash>"},"install_notes":"Record binary hash and dependency versions on the run machine."}
```

A mutable package tag, image tag, remote alias, or local path alone is not enough to establish reproducibility. Record a wheel/file hash, image digest, service version or dated model revision, or binary hash as appropriate.
