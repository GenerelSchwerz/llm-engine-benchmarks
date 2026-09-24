"""Validated, atomic manifest edits for the benchmark TUI."""

import json
import re
import tempfile
from pathlib import Path

from source_manifest import ROOT, load_sources

SOURCES = ROOT / "manifests/sources.json"
MODELS = ROOT / "manifests/models.json"
STATE = ROOT / ".benchmark-tui.json"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
HEX64 = re.compile(r"[0-9a-fA-F]{64}\Z")


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(data, handle, indent=2)
        handle.write("\n")
    temporary.replace(path)


def save_sources(items: list[dict], path: Path = SOURCES) -> None:
    data = {"schema_version": 2, "sources": items}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
        json.dump(data, handle)
        handle.flush()
        load_sources(Path(handle.name))
    atomic_json(path, data)


def load_models(path: Path = MODELS, sources_path: Path = SOURCES) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1 or not isinstance(data.get("models"), list):
        raise ValueError("models manifest needs schema_version 1 and a models array")
    known_engines = {item["id"] for item in load_sources(sources_path) if item["kind"] == "engine"}
    seen = set()
    for model in data["models"]:
        ident = model.get("id")
        if not isinstance(ident, str) or not ID.fullmatch(ident) or ident in seen:
            raise ValueError(f"invalid or duplicate model ID: {ident!r}")
        if not isinstance(model.get("artifact"), str) or not model["artifact"].strip():
            raise ValueError(f"model {ident} needs an artifact path, URL, or service ID")
        if not isinstance(model.get("context"), int) or model["context"] <= 0:
            raise ValueError(f"model {ident} needs a positive context")
        digest = model.get("sha256", "")
        if digest and (not isinstance(digest, str) or not HEX64.fullmatch(digest)):
            raise ValueError(f"model {ident} has an invalid SHA256")
        engine_ids = model.get("engine_ids", [])
        if not isinstance(engine_ids, list) or any(not isinstance(x, str) for x in engine_ids):
            raise ValueError(f"model {ident} needs a list of engine IDs")
        unknown = set(engine_ids) - known_engines
        if unknown:
            raise ValueError(f"model {ident} has unknown engines: {', '.join(sorted(unknown))}")
        seen.add(ident)
    return data["models"]


def save_models(models: list[dict], path: Path = MODELS, sources_path: Path = SOURCES) -> None:
    data = {"schema_version": 1, "models": models}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
        json.dump(data, handle)
        handle.flush()
        load_models(Path(handle.name), sources_path)
    atomic_json(path, data)


def load_state() -> dict:
    if not STATE.exists():
        return {"engines": [], "models": [], "suite_id": "", "check_updates": False}
    try:
        data = json.loads(STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"engines": [], "models": [], "suite_id": "", "check_updates": False}
    return data if isinstance(data, dict) else {"engines": [], "models": [], "suite_id": "", "check_updates": False}


def save_state(state: dict) -> None:
    atomic_json(STATE, state)
