"""Load and validate the editable engine/tool source list."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests/sources.json"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
SOURCE_TYPES = {"git", "package", "container", "remote", "local"}


def load_sources(path: Path = MANIFEST) -> list[dict]:
    data = json.loads(path.read_text())
    if data.get("schema_version") != 2 or not isinstance(data.get("sources"), list):
        raise ValueError("expected schema_version 2 and a sources array")
    seen = set()
    for item in data["sources"]:
        ident = item.get("id")
        source = item.get("source")
        if not isinstance(ident, str) or not ID.fullmatch(ident) or ident in seen:
            raise ValueError(f"invalid or duplicate source ID: {ident!r}")
        if item.get("kind") not in {"engine", "tool"} or not isinstance(source, dict):
            raise ValueError(f"invalid kind or source for {ident}")
        source_type = source.get("type")
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"invalid source type for {ident}: {source_type!r}")
        if source_type == "git":
            if (not isinstance(source.get("url"), str) or not source["url"]
                    or not isinstance(source.get("ref"), str) or not source["ref"]
                    or not isinstance(source.get("revision"), str)
                    or not SHA.fullmatch(source["revision"])):
                raise ValueError(f"Git source {ident} needs URL, ref, and 40-character commit")
        elif not isinstance(item.get("install_notes"), str) or not item["install_notes"].strip():
            raise ValueError(f"non-Git source {ident} needs install_notes")
        seen.add(ident)
    return data["sources"]


def destination(item: dict) -> Path:
    return ROOT / ("tools" if item["kind"] == "tool" else "sources") / item["id"]
