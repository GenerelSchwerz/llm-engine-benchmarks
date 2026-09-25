"""SQLite storage for human-entered engine and model setups."""

import json
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from source_manifest import ROOT, load_sources

DB = ROOT / "benchmark-catalog.sqlite3"
OLD_MODELS = ROOT / "manifests/models.json"
OLD_STATE = ROOT / ".benchmark-tui.json"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


@contextmanager
def connect(path: Path = DB) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS engines (
            id TEXT PRIMARY KEY, label TEXT NOT NULL, type TEXT NOT NULL,
            locator TEXT NOT NULL, ref_hint TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '', revision TEXT NOT NULL DEFAULT '',
            installed_path TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS models (
            id TEXT PRIMARY KEY, label TEXT NOT NULL, artifact TEXT NOT NULL,
            family TEXT NOT NULL DEFAULT '', context INTEGER,
            engine_ids TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS engine_overrides (
            id TEXT PRIMARY KEY, revision TEXT NOT NULL, installed_path TEXT NOT NULL,
            ref_hint TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requests (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('engine','model')),
            prompt TEXT NOT NULL, status TEXT NOT NULL
                CHECK(status IN ('pending','needs_input','ready','confirmed','canceled','failed')),
            message TEXT NOT NULL DEFAULT '', result_ids TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS request_results (
            request_id TEXT NOT NULL REFERENCES requests(id),
            result_id TEXT NOT NULL,
            PRIMARY KEY (request_id, result_id)
        );
        CREATE TABLE IF NOT EXISTS request_removals (
            request_id TEXT NOT NULL REFERENCES requests(id),
            item_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('engine','model')),
            deleted_install INTEGER NOT NULL DEFAULT 0,
            catalog_removed INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (request_id, item_id)
        );
        CREATE TABLE IF NOT EXISTS request_completion_signals (
            request_id TEXT PRIMARY KEY REFERENCES requests(id),
            message TEXT NOT NULL
        );
    """)
    columns = {row["name"] for row in db.execute("PRAGMA table_info(engines)")}
    for name in ("revision", "installed_path"):
        if name not in columns:
            db.execute(f"ALTER TABLE engines ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    removal_columns = {row["name"] for row in db.execute("PRAGMA table_info(request_removals)")}
    if "catalog_removed" not in removal_columns:
        db.execute("ALTER TABLE request_removals ADD COLUMN catalog_removed INTEGER NOT NULL DEFAULT 1")
    request_schema = db.execute("SELECT sql FROM sqlite_master WHERE name='requests'").fetchone()["sql"]
    if "'canceled'" not in request_schema:
        db.execute("""
            CREATE TABLE requests_new (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('engine','model')),
                prompt TEXT NOT NULL, status TEXT NOT NULL
                    CHECK(status IN ('pending','needs_input','ready','confirmed','canceled','failed')),
                message TEXT NOT NULL DEFAULT '', result_ids TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("INSERT INTO requests_new SELECT * FROM requests")
        db.execute("DROP TABLE requests")
        db.execute("ALTER TABLE requests_new RENAME TO requests")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def new_id(label: str, prefix: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:30] or prefix
    return f"{slug}-{uuid.uuid4().hex[:8]}"


def list_engines(path: Path = DB) -> list[dict]:
    with connect(path) as db:
        overrides = {row["id"]: dict(row) for row in db.execute("SELECT * FROM engine_overrides")}
    built_in = []
    for item in load_sources():
        if item["kind"] != "engine":
            continue
        source = item["source"]
        locator = next((source[key] for key in ("url", "name", "image", "model", "path_hint") if key in source), "")
        entry = {
            "id": item["id"], "label": item["id"], "type": source["type"],
            "locator": locator, "ref_hint": source.get("ref", ""),
            "notes": item.get("install_notes", ""), "revision": source.get("revision", source.get("version", "")),
            "installed_path": "", "built_in": True, "source": source,
        }
        if item["id"] in overrides:
            override = overrides[item["id"]]
            entry.update(revision=override["revision"], installed_path=override["installed_path"],
                         ref_hint=override["ref_hint"])
            entry["source"] = source | {"revision": override["revision"], "ref": override["ref_hint"]}
        built_in.append(entry)
    with connect(path) as db:
        custom = [dict(row) | {"built_in": False} for row in db.execute("SELECT * FROM engines ORDER BY label, id")]
    return built_in + custom


def list_models(path: Path = DB) -> list[dict]:
    with connect(path) as db:
        return [dict(row) | {"engine_ids": json.loads(row["engine_ids"])}
                for row in db.execute("SELECT * FROM models ORDER BY label, id")]


def save_engine(item: dict, path: Path = DB) -> str:
    locator = item.get("locator", "").strip()
    if not locator:
        raise ValueError("Enter a Git URL, package name, image, service ID, or executable path")
    if item.get("type") not in {"git", "package", "container", "remote", "local"}:
        raise ValueError("Choose an engine type")
    ident = item.get("id") or new_id(item.get("label") or locator.split("/")[-1], "engine")
    if not ID.fullmatch(ident):
        raise ValueError("Invalid engine ID")
    if any(x["id"] == ident and x["built_in"] for x in list_engines(path)):
        raise ValueError("Built-in engines are edited in manifests/sources.json")
    with connect(path) as db:
        old = db.execute("SELECT * FROM engines WHERE id=?", (ident,)).fetchone()
    same_locator = old and old["locator"] == locator and old["type"] == item["type"]
    revision = item.get("revision", old["revision"] if same_locator else "").strip()
    installed_path = item.get("installed_path", old["installed_path"] if same_locator else "").strip()
    with connect(path) as db:
        db.execute(
            "INSERT INTO engines(id,label,type,locator,ref_hint,notes,revision,installed_path) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "label=excluded.label, type=excluded.type, locator=excluded.locator, "
            "ref_hint=excluded.ref_hint, notes=excluded.notes, revision=excluded.revision, "
            "installed_path=excluded.installed_path",
            (ident, item.get("label", "").strip() or ident, item["type"], locator,
             item.get("ref_hint", "").strip(), item.get("notes", "").strip(), revision, installed_path),
        )
    return ident


def update_builtin_engine(ident: str, revision: str, installed_path: str,
                          ref_hint: str, path: Path = DB) -> str:
    entry = next((row for row in list_engines(path) if row["id"] == ident and row["built_in"]), None)
    if entry is None or entry["type"] != "git":
        raise ValueError("Only a built-in Git engine can use a local pin override")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        raise ValueError("Built-in Git override needs an exact commit SHA")
    checkout = Path(installed_path).expanduser()
    if not checkout.is_dir():
        raise ValueError("Built-in Git override needs an installed checkout")
    import subprocess
    result = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                            text=True, capture_output=True, check=False)
    if result.returncode or result.stdout.strip() != revision:
        raise ValueError("Checkout does not match the new revision")
    with connect(path) as db:
        db.execute("INSERT INTO engine_overrides VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                   "revision=excluded.revision, installed_path=excluded.installed_path, ref_hint=excluded.ref_hint",
                   (ident, revision.lower(), str(checkout.resolve()), ref_hint))
    return ident


def save_model(item: dict, path: Path = DB) -> str:
    artifact = item.get("artifact", "").strip()
    if not artifact:
        raise ValueError("Enter a model path, URL, or service ID")
    ids = item.get("engine_ids", [])
    known = {x["id"] for x in list_engines(path)}
    if not isinstance(ids, list) or set(ids) - known:
        raise ValueError("Select only known compatible engines")
    raw_context = item.get("context")
    if raw_context in (None, ""):
        context = None
    else:
        try:
            context = int(raw_context)
        except (TypeError, ValueError) as exc:
            raise ValueError("Context length must be a positive number") from exc
        if context <= 0:
            raise ValueError("Context length must be positive")
    ident = item.get("id") or new_id(item.get("label") or Path(artifact).name, "model")
    if not ID.fullmatch(ident):
        raise ValueError("Invalid model ID")
    with connect(path) as db:
        db.execute(
            "INSERT INTO models VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "label=excluded.label, artifact=excluded.artifact, family=excluded.family, "
            "context=excluded.context, engine_ids=excluded.engine_ids, notes=excluded.notes",
            (ident, item.get("label", "").strip() or ident, artifact,
             item.get("family", "").strip(), context, json.dumps(ids), item.get("notes", "").strip()),
        )
    return ident


def remove_engine(ident: str, path: Path = DB) -> None:
    if any(x["id"] == ident and x["built_in"] for x in list_engines(path)):
        raise ValueError("Built-in engines are edited in manifests/sources.json")
    if any(ident in x["engine_ids"] for x in list_models(path)):
        raise ValueError("This engine is referenced by a model; edit that model first")
    with connect(path) as db:
        db.execute("DELETE FROM engines WHERE id=?", (ident,))


def remove_model(ident: str, path: Path = DB) -> None:
    with connect(path) as db:
        db.execute("DELETE FROM models WHERE id=?", (ident,))


def load_state(path: Path = DB) -> dict:
    with connect(path) as db:
        row = db.execute("SELECT value FROM settings WHERE key='ui'").fetchone()
    return json.loads(row["value"]) if row else {"engines": [], "models": [], "suite_id": "", "check_updates": False}


def save_state(state: dict, path: Path = DB) -> None:
    with connect(path) as db:
        db.execute("INSERT INTO settings VALUES ('ui', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (json.dumps(state),))


def create_request(kind: str, prompt: str, path: Path = DB) -> str:
    if kind not in {"engine", "model"} or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Enter what the agent should find and install")
    ident = new_id(kind, "request")
    with connect(path) as db:
        db.execute("INSERT INTO requests(id,kind,prompt,status) VALUES (?,?,?,'pending')",
                   (ident, kind, prompt.strip()))
    return ident


def get_request(ident: str, path: Path = DB) -> dict:
    with connect(path) as db:
        row = db.execute("SELECT * FROM requests WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown setup request {ident}")
    return dict(row) | {"result_ids": json.loads(row["result_ids"])}


def attach_request_result(ident: str, result_id: str, path: Path = DB) -> None:
    request = get_request(ident, path)
    if request["status"] != "pending":
        raise ValueError("Request is not pending")
    known = {x["id"] for x in (list_engines(path) if request["kind"] == "engine" else list_models(path))}
    if result_id not in known:
        raise ValueError("Result ID does not match a saved item of the requested kind")
    with connect(path) as db:
        db.execute("INSERT OR IGNORE INTO request_results VALUES (?,?)", (ident, result_id))


def request_results(ident: str, path: Path = DB) -> list[str]:
    with connect(path) as db:
        return [row["result_id"] for row in db.execute(
            "SELECT result_id FROM request_results WHERE request_id=? ORDER BY rowid", (ident,)
        )]


def request_removals(ident: str, path: Path = DB) -> list[dict]:
    with connect(path) as db:
        return [dict(row) for row in db.execute(
            "SELECT item_id, kind, deleted_install, catalog_removed FROM request_removals WHERE request_id=? ORDER BY rowid",
            (ident,),
        )]


def signal_request_complete(ident: str, message: str, path: Path = DB) -> None:
    request = get_request(ident, path)
    if request["status"] != "pending" or not message.strip():
        raise ValueError("A pending request and completion message are required")
    if not request_results(ident, path) and not request_removals(ident, path):
        raise ValueError("Record an existing, added, updated, or removed item first")
    with connect(path) as db:
        db.execute("INSERT INTO request_completion_signals VALUES (?,?) ON CONFLICT(request_id) DO UPDATE SET "
                   "message=excluded.message", (ident, message.strip()))


def completion_signal(ident: str, path: Path = DB) -> str | None:
    with connect(path) as db:
        row = db.execute("SELECT message FROM request_completion_signals WHERE request_id=?", (ident,)).fetchone()
    return row["message"] if row else None


def remove_for_request(kind: str, item_id: str, request_id: str,
                       delete_install: bool = False, confirm_path: str = "",
                       path: Path = DB) -> None:
    request = get_request(request_id, path)
    if request["kind"] != kind or request["status"] != "pending":
        raise ValueError(f"Request must be a pending {kind} setup")
    items = list_engines(path) if kind == "engine" else list_models(path)
    item = next((row for row in items if row["id"] == item_id), None)
    if item is None:
        raise ValueError(f"Unknown {kind} ID: {item_id}")
    built_in = kind == "engine" and item["built_in"]
    if built_in and not delete_install:
        raise ValueError("Built-in engine definitions remain available; use --delete-install to remove its local checkout")
    if kind == "engine" and any(item_id in row["engine_ids"] for row in list_models(path)):
        raise ValueError("Engine is referenced by a model; edit or remove that model first")
    target = None
    if delete_install:
        saved = ((item["installed_path"] or str(ROOT / "sources" / item_id)) if kind == "engine" and item["type"] == "git"
                 else (item["installed_path"] or item["locator"]) if kind == "engine" else item["artifact"])
        if not saved or not Path(saved).is_absolute():
            raise ValueError("File removal requires an absolute saved install path")
        original = Path(saved)
        if original.is_symlink() or not original.exists():
            raise ValueError("Install path must exist and cannot be a symlink")
        target = original.resolve(strict=True)
        if not confirm_path or Path(confirm_path).resolve() != target:
            raise ValueError("--confirm-path must match the saved install path")
        protected = (Path.home().resolve(), ROOT.resolve(), Path.cwd().resolve())
        if target == Path(target.anchor) or any(target == root or target in root.parents for root in protected):
            raise ValueError("Refusing to remove a protected directory")
        allowed = (Path.home().resolve(), Path("/mnt"), Path("/media"), Path("/srv"), Path("/tmp"))
        if not any(root in target.parents for root in allowed):
            raise ValueError("Install path is outside allowed user data locations")
        if ROOT.resolve() in target.parents and (ROOT / "sources").resolve() not in target.parents:
            raise ValueError("Refusing to remove project files outside sources/")
        if kind == "engine" and item["type"] not in {"git", "local"}:
            raise ValueError("Automatic file removal supports only Git or local engines")
        others = [row for row in items if row["id"] != item_id]
        other_paths = [((row["installed_path"] or row["locator"]) if kind == "engine" else row["artifact"])
                       for row in others]
        shared = any(value and Path(value).is_absolute() and
                     (target == Path(value).resolve() or target in Path(value).resolve().parents or
                      Path(value).resolve() in target.parents)
                     for value in other_paths)
        if shared:
            raise ValueError("Install path is shared by another catalog entry")
        if kind == "engine" and item["type"] == "git":
            import subprocess
            state = subprocess.run(["git", "-C", str(target), "status", "--porcelain"],
                                   text=True, capture_output=True, check=False)
            if state.returncode or state.stdout.strip():
                raise ValueError("Refusing to remove a Git checkout with uncommitted or untracked files")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    with connect(path) as db:
        if not built_in:
            table = "engines" if kind == "engine" else "models"
            db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
        else:
            db.execute("DELETE FROM engine_overrides WHERE id=?", (item_id,))
        db.execute("INSERT OR REPLACE INTO request_removals VALUES (?,?,?,?,?)",
                   (request_id, item_id, kind, int(delete_install), int(not built_in)))
        db.execute("DELETE FROM request_results WHERE request_id=? AND result_id=?", (request_id, item_id))


def latest_request(kind: str, path: Path = DB) -> dict | None:
    with connect(path) as db:
        row = db.execute("SELECT id FROM requests WHERE kind=? ORDER BY updated_at DESC, rowid DESC LIMIT 1",
                         (kind,)).fetchone()
    return get_request(row["id"], path) if row else None


def resolve_request(ident: str, status: str, message: str,
                    result_ids: list[str] | None = None, path: Path = DB) -> None:
    request = get_request(ident, path)
    if request["status"] == "confirmed":
        raise ValueError("Confirmed request cannot be changed")
    if status not in {"ready", "needs_input", "canceled", "failed"} or not isinstance(message, str) or not message.strip():
        raise ValueError("Resolution needs ready, needs_input, canceled, or failed and a clear message")
    if result_ids is not None and (not isinstance(result_ids, list) or any(not isinstance(x, str) for x in result_ids)):
        raise ValueError("Result IDs must be a list of strings")
    ids = result_ids or []
    if status == "ready":
        removals = request_removals(ident, path)
        if not ids and not removals:
            raise ValueError("Ready request needs a saved result ID or a recorded removal")
        known_now = {x["id"] for x in (list_engines(path) if request["kind"] == "engine" else list_models(path))}
        if any(row["catalog_removed"] and row["item_id"] in known_now for row in removals):
            raise ValueError("Removed item is still in the catalog")
        if any(not row["catalog_removed"] and (ROOT / "sources" / row["item_id"]).exists() for row in removals):
            raise ValueError("Built-in engine checkout still exists")
        known = {x["id"] for x in (list_engines(path) if request["kind"] == "engine" else list_models(path))}
        if set(ids) - known:
            raise ValueError("Ready request names unknown result IDs")
        for item in (list_engines(path) if request["kind"] == "engine" else list_models(path)):
            if item["id"] in ids:
                locator = item["locator"] if request["kind"] == "engine" else item["artifact"]
                if locator.startswith(("/", "./", "../", "~")) and not Path(locator).expanduser().exists():
                    raise ValueError(f"Local result does not exist: {locator}")
                if request["kind"] == "engine":
                    if item["type"] == "git":
                        checkout = (
                            Path(item["installed_path"]).expanduser() if item["built_in"] and item["installed_path"] else
                            ROOT / "sources" / item["id"] if item["built_in"] else
                            Path(item["installed_path"]).expanduser() if item["installed_path"] else None
                        )
                        if not checkout or not checkout.is_dir():
                            raise ValueError("Git result needs an installed checkout path")
                        if not re.fullmatch(r"[0-9a-fA-F]{40}", item["revision"]):
                            raise ValueError("Git result needs an exact commit SHA")
                        import subprocess
                        result = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                                                text=True, capture_output=True, check=False)
                        if result.returncode or result.stdout.strip() != item["revision"]:
                            raise ValueError("Git checkout does not match the recorded commit")
                    elif item["type"] == "local" and not Path(item["locator"]).expanduser().is_file():
                        raise ValueError("Local engine executable does not exist")
                    elif item["type"] in {"package", "container", "remote"} and not item["revision"]:
                        raise ValueError("Result needs an exact package, image, or service version")
    elif ids:
        raise ValueError("Only ready requests can include completed result IDs")
    with connect(path) as db:
        db.execute("UPDATE requests SET status=?, message=?, result_ids=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                   (status, message.strip(), json.dumps(ids), ident))


def confirm_request(ident: str, path: Path = DB) -> list[str]:
    request = get_request(ident, path)
    if request["status"] != "ready":
        raise ValueError("Only a ready request can be confirmed")
    with connect(path) as db:
        db.execute("UPDATE requests SET status='confirmed', updated_at=CURRENT_TIMESTAMP WHERE id=?", (ident,))
    return request["result_ids"]


def answer_request(ident: str, answer: str, path: Path = DB) -> None:
    request = get_request(ident, path)
    if request["status"] != "needs_input" or not answer.strip():
        raise ValueError("Enter an answer to the agent's question")
    with connect(path) as db:
        db.execute("UPDATE requests SET prompt=?, status='pending', message='', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                   (request["prompt"] + "\nUser clarification: " + answer.strip(), ident))
        db.execute("DELETE FROM request_results WHERE request_id=?", (ident,))
        db.execute("DELETE FROM request_removals WHERE request_id=?", (ident,))
        db.execute("DELETE FROM request_completion_signals WHERE request_id=?", (ident,))


def migrate_old_files(path: Path = DB, old_models: Path = OLD_MODELS, old_state: Path = OLD_STATE) -> None:
    """Import previous local JSON once; retain the originals as backups."""
    with connect(path) as db:
        if db.execute("SELECT 1 FROM settings WHERE key='migration_v1'").fetchone():
            return
    if old_models.exists():
        for old in json.loads(old_models.read_text()).get("models", []):
            save_model({
                "id": old["id"], "label": old.get("family") or old["id"],
                "artifact": old["artifact"], "family": old.get("family", ""),
                "context": old.get("context"), "engine_ids": old.get("engine_ids", []),
                "notes": old.get("notes", ""),
            }, path)
    if old_state.exists():
        save_state(json.loads(old_state.read_text()), path)
    with connect(path) as db:
        db.execute("INSERT INTO settings VALUES ('migration_v1', 'done')")
