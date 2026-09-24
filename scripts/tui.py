#!/usr/bin/env python3
"""Minimal terminal UI for engine, model, and suite setup."""

import json
import shutil
import subprocess
import sys

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import (
    Button, Checkbox, Footer, Header, Input, Label, RichLog, Select,
    SelectionList, Static, TabbedContent, TabPane,
)

from source_manifest import ROOT, load_sources
from tui_data import load_models, load_state, save_models, save_sources, save_state

TYPES = ("git", "package", "container", "remote", "local")
FIELD_LABELS = {
    "git": ("Git URL", "Branch/ref", "Commit SHA"),
    "package": ("Package name", "Manager (e.g. pip)", "Version"),
    "container": ("Image@sha256:digest", "", ""),
    "remote": ("Service model ID", "Provider", "Service version"),
    "local": ("Executable path", "", "Binary SHA256"),
}


class BenchmarkApp(App[None]):
    TITLE = "LLM Benchmarks"
    SUB_TITLE = "engines · models · suite"
    BINDINGS = [("q", "quit", "Quit")]
    CSS = """
    Screen { background: $surface; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 1 2; }
    .section-title { text-style: bold; margin: 0 0 1 0; }
    .field-label { margin: 0 0 0 0; color: $text-muted; }
    Input, Select { margin: 0 0 1 0; }
    .picker { height: 9; border: round $primary; margin: 0 0 1 0; }
    .form { height: 1fr; }
    .buttons { height: 3; margin: 1 0; }
    Button { margin-right: 1; }
    #messages { height: 5; border-top: solid $primary; }
    #suite-summary { margin: 1 0; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.sources = load_sources()
        self.models = load_models()
        self.state = load_state()
        self.loading = True
        self.pending_delete: tuple[str, str] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="engines"):
            with TabPane("Engines", id="engines"):
                yield Label("Choose engines for this suite (Space toggles selection)", classes="section-title")
                yield SelectionList(id="engine-list", classes="picker")
                with Horizontal(classes="buttons"):
                    yield Button("Install selected", id="install", variant="primary")
                    yield Button("Check selected", id="check")
                with VerticalScroll(classes="form"):
                    yield Label("Add or edit an engine", classes="section-title")
                    yield Select([], id="engine-editor", prompt="New engine")
                    yield Label("ID", classes="field-label")
                    yield Input(id="engine-id", placeholder="unique-engine-id")
                    yield Label("Source type", classes="field-label")
                    yield Select([(x.title(), x) for x in TYPES], id="engine-type", value="git", allow_blank=False)
                    yield Label("Git URL", id="locator-label", classes="field-label")
                    yield Input(id="engine-locator", placeholder="https://example.org/engine.git")
                    yield Label("Branch/ref", id="ref-label", classes="field-label")
                    yield Input(id="engine-ref", placeholder="main")
                    yield Label("Commit SHA", id="revision-label", classes="field-label")
                    yield Input(id="engine-revision", placeholder="immutable revision")
                    yield Label("Install notes (required for non-Git)", classes="field-label")
                    yield Input(id="engine-notes", placeholder="reproducible install/version instructions")
                    with Horizontal(classes="buttons"):
                        yield Button("New", id="engine-new")
                        yield Button("Save", id="engine-save", variant="success")
                        yield Button("Remove", id="engine-remove", variant="error")
            with TabPane("Models", id="models"):
                yield Label("Choose model setups for this suite (Space toggles selection)", classes="section-title")
                yield SelectionList(id="model-list", classes="picker")
                with VerticalScroll(classes="form"):
                    yield Label("Add or edit a model artifact", classes="section-title")
                    yield Select([], id="model-editor", prompt="New model")
                    for label, input_id, placeholder in [
                        ("ID", "model-id", "model-id"),
                        ("Family", "model-family", "model family"),
                        ("Artifact path, URL, or service ID", "model-artifact", "/models/model.gguf"),
                        ("Artifact revision", "model-revision", "release or service revision"),
                        ("SHA256 (file artifacts)", "model-sha", "optional 64-character SHA256"),
                        ("Tokenizer path or ID", "model-tokenizer", "tokenizer"),
                        ("Quantization or dtype", "model-dtype", "e.g. Q4_K_M or bf16"),
                        ("Context length", "model-context", "8192"),
                        ("Draft artifact (optional)", "model-draft", "path or URL"),
                        ("Applicable engine IDs", "model-engines", "comma-separated IDs"),
                        ("Notes", "model-notes", "setup or compatibility notes"),
                    ]:
                        yield Label(label, classes="field-label")
                        yield Input(id=input_id, placeholder=placeholder)
                    with Horizontal(classes="buttons"):
                        yield Button("New", id="model-new")
                        yield Button("Save", id="model-save", variant="success")
                        yield Button("Remove", id="model-remove", variant="error")
            with TabPane("Suite", id="suite"):
                yield Label("Run one suite at a time", classes="section-title")
                yield Label("Suite ID", classes="field-label")
                yield Input(id="suite-id", placeholder="e.g. september-llm-sweep")
                yield Checkbox("Check upstream updates during preparation", id="check-updates")
                yield Static(id="suite-summary")
                with Horizontal(classes="buttons"):
                    yield Button("Prepare with Codex", id="prepare", variant="primary")
                    yield Button("Run frozen plan", id="run")
                yield Static("Preparation reviews selected engines and models. Run uses one execution agent; neither action publishes results.")
        yield RichLog(id="messages", highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_engines()
        self.refresh_models()
        self.query_one("#suite-id", Input).value = str(self.state.get("suite_id", ""))
        self.query_one("#check-updates", Checkbox).value = bool(self.state.get("check_updates", False))
        self.loading = False
        self.update_summary()
        self.message("Ready. Select engines and models, or add your own.")

    def message(self, value: str) -> None:
        self.query_one("#messages", RichLog).write(value)

    def selected(self, widget_id: str) -> list[str]:
        return list(self.query_one(widget_id, SelectionList).selected)

    def remember(self) -> None:
        if self.loading:
            return
        self.state = {
            "engines": self.selected("#engine-list"),
            "models": self.selected("#model-list"),
            "suite_id": self.query_one("#suite-id", Input).value.strip(),
            "check_updates": self.query_one("#check-updates", Checkbox).value,
        }
        save_state(self.state)
        self.update_summary()

    def update_summary(self) -> None:
        engines = self.selected("#engine-list")
        models = self.selected("#model-list")
        self.query_one("#suite-summary", Static).update(
            f"Engines: {', '.join(engines) or 'none'}\n"
            f"Models: {', '.join(models) or 'none'}\n"
            f"Upstream updates: {'check' if self.query_one('#check-updates', Checkbox).value else 'skip'}"
        )

    def refresh_engines(self, editor_id: str | None = None) -> None:
        self.sources = load_sources()
        engines = [x for x in self.sources if x["kind"] == "engine"]
        previous = set(self.state.get("engines", [])) | set(self.selected("#engine-list"))
        picker = self.query_one("#engine-list", SelectionList)
        picker.set_options([
            (f"{x['id']}  ·  {x['source']['type']}  ·  {x['source'].get('revision', x['source'].get('version', 'manual'))[:12]}", x["id"], x["id"] in previous)
            for x in engines
        ])
        editor = self.query_one("#engine-editor", Select)
        editor.set_options([(x["id"], x["id"]) for x in engines])
        if editor_id:
            editor.value = editor_id
            self.load_engine(editor_id)
        self.update_summary()

    def refresh_models(self, editor_id: str | None = None) -> None:
        self.models = load_models()
        previous = set(self.state.get("models", [])) | set(self.selected("#model-list"))
        self.query_one("#model-list", SelectionList).set_options([
            (f"{x['id']}  ·  {x.get('family', '')}  ·  {x.get('quant_or_dtype', '')}", x["id"], x["id"] in previous)
            for x in self.models
        ])
        editor = self.query_one("#model-editor", Select)
        editor.set_options([(x["id"], x["id"]) for x in self.models])
        if editor_id:
            editor.value = editor_id
            self.load_model(editor_id)
        self.update_summary()

    def text(self, ident: str) -> str:
        return self.query_one(f"#{ident}", Input).value.strip()

    def fill(self, prefix: str, values: dict[str, str]) -> None:
        for key, value in values.items():
            self.query_one(f"#{prefix}-{key}", Input).value = value

    def load_engine(self, ident: str) -> None:
        item = next((x for x in self.sources if x["id"] == ident), None)
        if item is None:
            return
        source = item["source"]
        kind = source["type"]
        self.query_one("#engine-type", Select).value = kind
        locator = source.get({"git":"url", "package":"name", "container":"image", "remote":"model", "local":"path_hint"}[kind], "")
        ref = source.get({"git":"ref", "package":"manager", "remote":"provider"}.get(kind, ""), "")
        revision = source.get({"git":"revision", "package":"version", "remote":"version", "local":"sha256"}.get(kind, ""), "")
        self.fill("engine", {"id":ident, "locator":locator, "ref":ref, "revision":revision, "notes":item.get("install_notes", "")})

    def load_model(self, ident: str) -> None:
        item = next((x for x in self.models if x["id"] == ident), None)
        if item is None:
            return
        self.fill("model", {
            "id":ident, "family":item.get("family", ""), "artifact":item["artifact"],
            "revision":item.get("revision", ""), "sha":item.get("sha256", ""),
            "tokenizer":item.get("tokenizer", ""), "dtype":item.get("quant_or_dtype", ""),
            "context":str(item["context"]), "draft":item.get("draft_artifact", ""),
            "engines":", ".join(item.get("engine_ids", [])), "notes":item.get("notes", ""),
        })

    def on_select_changed(self, event: Select.Changed) -> None:
        if self.loading:
            return
        ident = event.select.id
        if ident == "engine-editor" and isinstance(event.value, str):
            self.load_engine(event.value)
            self.pending_delete = None
        elif ident == "model-editor" and isinstance(event.value, str):
            self.load_model(event.value)
            self.pending_delete = None
        elif ident == "engine-type" and isinstance(event.value, str):
            labels = FIELD_LABELS[event.value]
            for target, label in zip(("locator-label", "ref-label", "revision-label"), labels):
                self.query_one(f"#{target}", Label).update(label)

    def on_selection_list_selected_changed(self, _event: SelectionList.SelectedChanged) -> None:
        self.remember()

    def on_checkbox_changed(self, _event: Checkbox.Changed) -> None:
        self.remember()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "suite-id":
            self.remember()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = event.button.id
        try:
            if action == "engine-new":
                self.query_one("#engine-editor", Select).value = Select.NULL
                self.query_one("#engine-type", Select).value = "git"
                self.fill("engine", {x:"" for x in ("id","locator","ref","revision","notes")})
            elif action == "model-new":
                self.query_one("#model-editor", Select).value = Select.NULL
                self.fill("model", {x:"" for x in ("id","family","artifact","revision","sha","tokenizer","dtype","context","draft","engines","notes")})
            elif action == "engine-save":
                self.save_engine()
            elif action == "model-save":
                self.save_model()
            elif action in {"engine-remove", "model-remove"}:
                self.remove_item("engine" if action == "engine-remove" else "model")
            elif action in {"install", "check"}:
                selected = self.selected("#engine-list")
                if not selected:
                    raise ValueError("Select at least one engine")
                self.source_action(action, selected, self.query_one("#check-updates", Checkbox).value)
            elif action in {"prepare", "run"}:
                self.launch_agent(action)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            self.message(f"[red]{exc}[/red]")
            self.notify(str(exc), severity="error")

    def save_engine(self) -> None:
        ident = self.text("engine-id")
        kind = self.query_one("#engine-type", Select).value
        if not isinstance(kind, str):
            raise ValueError("Choose a source type")
        locator, ref, revision, notes = (self.text(f"engine-{x}") for x in ("locator", "ref", "revision", "notes"))
        if not locator:
            raise ValueError("Source location is required")
        if kind in {"package", "remote"} and not ref:
            raise ValueError("Package manager or service provider is required")
        if kind == "git":
            source = {"type":kind, "url":locator, "ref":ref, "revision":revision}
        elif kind == "package":
            source = {"type":kind, "name":locator, "manager":ref, "version":revision}
        elif kind == "container":
            image, separator, digest = locator.rpartition("@sha256:")
            if not separator or not image or len(digest) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in digest):
                raise ValueError("Use an image@sha256: digest with 64 hex characters")
            source = {"type":kind, "image":locator}
        elif kind == "remote":
            source = {"type":kind, "model":locator, "provider":ref, "version":revision}
        else:
            source = {"type":kind, "path_hint":locator, "sha256":revision}
        if kind in {"package", "remote", "local"} and not revision:
            raise ValueError("An immutable version or SHA256 is required")
        if kind == "local" and (len(revision) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in revision)):
            raise ValueError("Local binary SHA256 must have 64 hex characters")
        item = {"id":ident, "kind":"engine", "source":source}
        if notes:
            item["install_notes"] = notes
        old_value = self.query_one("#engine-editor", Select).value
        old_id = old_value if isinstance(old_value, str) else None
        if old_id and old_id != ident and any(x["id"] == ident for x in self.sources):
            raise ValueError(f"Engine ID {ident} already exists")
        if old_id and old_id != ident and any(old_id in model.get("engine_ids", []) for model in self.models):
            raise ValueError(f"Engine {old_id} is used by a model; update that setup before renaming")
        items = [x for x in self.sources if x["id"] != old_id] if old_id else list(self.sources)
        items.append(item)
        save_sources(items)
        self.refresh_engines(ident)
        self.message(f"Saved engine {ident}")

    def save_model(self) -> None:
        ident = self.text("model-id")
        engine_ids = [x.strip() for x in self.text("model-engines").split(",") if x.strip()]
        try:
            context = int(self.text("model-context"))
        except ValueError as exc:
            raise ValueError("Context length must be a positive integer") from exc
        item = {
            "id":ident, "family":self.text("model-family"), "artifact":self.text("model-artifact"),
            "revision":self.text("model-revision"), "sha256":self.text("model-sha"),
            "tokenizer":self.text("model-tokenizer"), "quant_or_dtype":self.text("model-dtype"),
            "context":context, "draft_artifact":self.text("model-draft"),
            "engine_ids":engine_ids, "notes":self.text("model-notes"),
        }
        old_value = self.query_one("#model-editor", Select).value
        old_id = old_value if isinstance(old_value, str) else None
        if old_id and old_id != ident and any(x["id"] == ident for x in self.models):
            raise ValueError(f"Model ID {ident} already exists")
        items = [x for x in self.models if x["id"] != old_id] if old_id else list(self.models)
        items.append(item)
        save_models(items)
        self.refresh_models(ident)
        self.message(f"Saved model {ident}")

    def remove_item(self, kind: str) -> None:
        editor = self.query_one(f"#{kind}-editor", Select)
        ident = editor.value
        if not isinstance(ident, str):
            raise ValueError(f"Choose a {kind} to remove")
        marker = (kind, ident)
        if self.pending_delete != marker:
            self.pending_delete = marker
            self.message(f"Press Remove again to delete {kind} {ident}")
            return
        self.pending_delete = None
        if kind == "engine":
            if any(ident in model.get("engine_ids", []) for model in self.models):
                raise ValueError(f"Engine {ident} is referenced by a model setup")
            save_sources([x for x in self.sources if x["id"] != ident])
            self.state["engines"] = [x for x in self.state.get("engines", []) if x != ident]
            self.refresh_engines()
        else:
            save_models([x for x in self.models if x["id"] != ident])
            self.state["models"] = [x for x in self.state.get("models", []) if x != ident]
            self.refresh_models()
        editor.value = Select.NULL
        self.message(f"Removed {kind} {ident}")
        self.remember()

    @work(thread=True, exclusive=True)
    def source_action(self, action: str, selected: list[str], updates: bool) -> None:
        command = [sys.executable, str(ROOT / "scripts" / ("install_sources.py" if action == "install" else "check_sources.py"))]
        for ident in selected:
            command.extend(("--id", ident))
        if action == "check" and updates:
            command.append("--remote")
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        if action == "check" and result.stdout:
            try:
                entries = json.loads(result.stdout)["sources"]
                lines = [f"{x['id']}: {x['local_status']}" + (f", remote {x['remote_status']}" if updates else "") for x in entries]
                output = "\n".join(lines)
            except (ValueError, KeyError):
                output = result.stdout.strip()
        else:
            output = result.stdout.strip()
        if result.returncode:
            output += f"\n{result.stderr.strip()}\nExit code {result.returncode}"
        self.call_from_thread(self.message, output or f"{action} complete")

    def launch_agent(self, stage: str) -> None:
        self.remember()
        suite_id = self.text("suite-id")
        engines = self.selected("#engine-list")
        models = self.selected("#model-list")
        if not suite_id:
            raise ValueError("Enter a suite ID")
        if not engines or not models:
            raise ValueError("Select at least one engine and one model")
        incompatible = [
            model["id"] for model in self.models
            if model["id"] in models and model.get("engine_ids")
            and not set(model["engine_ids"]).intersection(engines)
        ]
        if incompatible:
            raise ValueError(f"Selected models have no selected compatible engine: {', '.join(incompatible)}")
        if shutil.which("codex") is None:
            raise ValueError("Codex CLI is not installed or not on PATH")
        command = [sys.executable, str(ROOT / "scripts/start_codex.py"), stage, suite_id]
        for ident in engines:
            command.extend(("--engine", ident))
        for ident in models:
            command.extend(("--model", ident))
        if stage == "prepare":
            command.append("--check-updates" if self.query_one("#check-updates", Checkbox).value else "--no-check-updates")
        self.message(f"Starting Codex {stage} for {suite_id}")
        with self.suspend():
            completed = subprocess.run(command, cwd=ROOT, check=False)
        self.message(f"Codex exited with status {completed.returncode}")


def main() -> None:
    try:
        BenchmarkApp().run()
    except (ValueError, OSError) as exc:
        print(f"Cannot start benchmark TUI: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
