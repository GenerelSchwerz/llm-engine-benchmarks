#!/usr/bin/env python3
"""Small terminal UI for choosing engines and models before agent preparation."""

import asyncio
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import (
    Button, Checkbox, Footer, Header, Input, Label, RichLog, Select,
    SelectionList, Static, TabbedContent, TabPane, Tabs,
)
from textual_tty import Terminal

from source_manifest import ROOT
from start_codex import make_prompt
from suite_store import create_suite, show_suite, validate_suite
from tui_data import (
    answer_request, completion_signal, confirm_request, create_request, get_request, latest_request,
    list_engines, list_models, load_state, migrate_old_files, remove_engine,
    remove_model, request_removals, request_results, resolve_request, save_engine, save_model, save_state,
)

TYPES = ("git", "package", "container", "remote", "local")
LOCATOR_LABELS = {
    "git": "Git URL", "package": "Package name", "container": "Container image",
    "remote": "Service model ID or endpoint", "local": "Executable path",
}


class SearchableSelectionList(SelectionList):
    """Keep keyboard search on the picker the pointer is over."""

    def on_enter(self) -> None:
        self.focus()

    def on_mouse_move(self) -> None:
        if not self.has_focus:
            self.focus()

    def on_key(self, event) -> None:
        if event.key in {"backspace", "escape"}:
            self.app.change_picker_filter(self.id, event.key)
        elif event.character and event.character.isprintable() and not event.character.isspace():
            self.app.change_picker_filter(self.id, event.character)
        else:
            return
        event.prevent_default()
        event.stop()


class BenchmarkApp(App[None]):
    TITLE = "LLM Benchmarks"
    SUB_TITLE = "engines · models · suite"
    BINDINGS = [("q", "quit", "Quit"), Binding("ctrl+g", "focus_agent_tabs", "Leave agent", priority=True)]
    CSS = """
    Screen { background: $surface; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 1 2; }
    .section-title { text-style: bold; margin-bottom: 1; }
    .field-label { color: $text-muted; }
    Input, Select { margin-bottom: 1; }
    .picker { height: 17; border: round $primary; margin-bottom: 1; }
    .picker-filter { color: $text-muted; height: 1; }
    .form { height: 1fr; }
    .buttons { height: 3; margin: 1 0; }
    Button { margin-right: 1; }
    #messages { height: 5; border-top: solid $primary; }
    #suite-summary { margin: 1 0; }
    .agent-panel { height: 1fr; }
    Terminal { height: 1fr; }
    .request-status { margin: 1 0; }
    .mode-button { dock: bottom; height: 3; margin: 1 0 0 0; }
    #agent-tabs { height: 1fr; }
    """

    def __init__(self) -> None:
        super().__init__()
        migrate_old_files()
        self.engines = list_engines()
        self.models = list_models()
        self.state = load_state()
        self.loading = True
        self.pending_delete: tuple[str, str] | None = None
        self.edit_engine_id: str | None = None
        self.edit_model_id: str | None = None
        self.mode = {
            "engine": self.state.get("engine_mode", "agent"),
            "model": self.state.get("model_mode", "agent"),
        }
        self.active_requests: set[str] = set()
        self.terminals: dict[str, tuple[str, ...]] = {}
        self.picker_filters = {"engine": "", "model": ""}
        self.selection_cache = {
            "engine": set(self.state.get("engines", [])),
            "model": set(self.state.get("models", [])),
        }

    def embedded_terminal_available(self) -> bool:
        return (self.console.color_system is not None
                and os.environ.get("TERM", "").lower() not in {"", "dumb", "unknown"}
                and "NO_COLOR" not in os.environ
                and os.environ.get("CLICOLOR") != "0")

    def action_focus_agent_tabs(self) -> None:
        self.query_one("#agent-tabs Tabs", Tabs).focus()

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="engines"):
            with TabPane("Engines", id="engines"):
                yield Label("Choose engines (Space toggles selection)", classes="section-title")
                yield Static("Hover and type to filter · Backspace edits · Esc clears", id="engine-filter", classes="picker-filter")
                yield SearchableSelectionList(id="engine-list", classes="picker")
                with VerticalScroll(id="engine-agent", classes="agent-panel"):
                    yield Label("Tell the agent what to install", classes="section-title")
                    yield Input(id="engine-request", placeholder="Install theTom's fork from GitHub")
                    with Horizontal(classes="buttons"):
                        yield Button("Ask agent", id="engine-ask", variant="primary")
                        yield Button("Confirm result", id="engine-confirm", variant="success")
                    yield Static(id="engine-agent-status", classes="request-status")
                with VerticalScroll(id="engine-manual", classes="form"):
                    yield Label("Add an engine", classes="section-title")
                    yield Label("Name (optional)", classes="field-label")
                    yield Input(id="engine-label", placeholder="e.g. My fast engine")
                    yield Label("Type", classes="field-label")
                    yield Select([(x.title(), x) for x in TYPES], id="engine-type", value="git", allow_blank=False)
                    yield Label("Git URL", id="locator-label", classes="field-label")
                    yield Input(id="engine-locator", placeholder="https://example.org/engine.git")
                    yield Label("Branch or reference (optional)", classes="field-label")
                    yield Input(id="engine-ref", placeholder="leave empty to let the agent determine it")
                    yield Label("Notes (optional)", classes="field-label")
                    yield Input(id="engine-notes", placeholder="anything the agent should know")
                    with Horizontal(classes="buttons"):
                        yield Button("New", id="engine-new")
                        yield Button("Edit selected", id="engine-edit")
                        yield Button("Save", id="engine-save", variant="success")
                        yield Button("Remove", id="engine-remove", variant="error")
                yield Button("Switch to manual setup", id="engine-mode", classes="mode-button")
            with TabPane("Models", id="models"):
                yield Label("Choose model setups (Space toggles selection)", classes="section-title")
                yield Static("Hover and type to filter · Backspace edits · Esc clears", id="model-filter", classes="picker-filter")
                yield SearchableSelectionList(id="model-list", classes="picker")
                yield Static("No models saved yet.", id="model-empty")
                with VerticalScroll(id="model-agent", classes="agent-panel"):
                    yield Label("Tell the agent what to install", classes="section-title")
                    yield Input(id="model-request", placeholder="Install Qwen 35B Q4_K_M and Qwen 27B from my local system")
                    with Horizontal(classes="buttons"):
                        yield Button("Ask agent", id="model-ask", variant="primary")
                        yield Button("Confirm result", id="model-confirm", variant="success")
                    yield Static(id="model-agent-status", classes="request-status")
                with VerticalScroll(id="model-manual", classes="form"):
                    yield Label("Add a model", classes="section-title")
                    yield Label("Name (optional)", classes="field-label")
                    yield Input(id="model-label", placeholder="e.g. Qwen local GGUF")
                    yield Label("Model path, URL, or service ID", classes="field-label")
                    yield Input(id="model-artifact", placeholder="/models/model.gguf")
                    yield Label("Family (optional)", classes="field-label")
                    yield Input(id="model-family", placeholder="the agent can identify this")
                    yield Label("Context length (optional)", classes="field-label")
                    yield Input(id="model-context", placeholder="the agent can determine this")
                    yield Label("Compatible engine IDs (optional)", classes="field-label")
                    yield Input(id="model-engines", placeholder="leave empty to let the agent check")
                    yield Label("Notes (optional)", classes="field-label")
                    yield Input(id="model-notes", placeholder="anything the agent should know")
                    with Horizontal(classes="buttons"):
                        yield Button("New", id="model-new")
                        yield Button("Edit selected", id="model-edit")
                        yield Button("Save", id="model-save", variant="success")
                        yield Button("Remove", id="model-remove", variant="error")
                yield Button("Switch to manual setup", id="model-mode", classes="mode-button")
            with TabPane("Suite", id="suite"):
                yield Label("Run one suite at a time", classes="section-title")
                yield Label("Suite name", classes="field-label")
                yield Input(id="suite-id", placeholder="e.g. september-sweep")
                yield Checkbox("Check upstream updates during preparation", id="check-updates")
                yield Static(id="suite-summary")
                with Horizontal(classes="buttons"):
                    yield Button("Prepare with Codex", id="prepare", variant="primary")
                    yield Button("Run frozen plan", id="run")
                yield Static("The agent resolves versions, hashes, tokenizer, and per-model commands. Code validates the saved plan.")
            with TabPane("Agents", id="agents"):
                with TabbedContent(id="agent-tabs"):
                    with TabPane("Overview", id="agent-overview"):
                        yield Static("Agent output appears here while setup requests run.")
        yield RichLog(id="messages", highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_engines()
        self.refresh_models()
        self.query_one("#suite-id", Input).value = self.state.get("suite_id", "")
        self.query_one("#check-updates", Checkbox).value = bool(self.state.get("check_updates", False))
        self.loading = False
        self.update_modes()
        self.refresh_request("engine")
        self.refresh_request("model")
        self.set_interval(1, self.poll_requests)
        self.update_summary()
        self.message("Ready. Add or select an engine and model, then prepare the suite.")

    def message(self, value: str) -> None:
        self.query_one("#messages", RichLog).write(value)

    def selected(self, ident: str) -> list[str]:
        kind = "engine" if ident == "#engine-list" else "model"
        picker = self.query_one(ident, SelectionList)
        visible = {option.value for option in picker.options}
        chosen = (self.selection_cache[kind] - visible) | set(picker.selected)
        items = self.engines if kind == "engine" else self.models
        return [item["id"] for item in items if item["id"] in chosen]

    def change_picker_filter(self, picker_id: str | None, key: str) -> None:
        if picker_id not in {"engine-list", "model-list"}:
            return
        kind = picker_id.split("-")[0]
        self.selection_cache[kind] = set(self.selected(f"#{picker_id}"))
        current = self.picker_filters[kind]
        self.picker_filters[kind] = ("" if key == "escape" else current[:-1] if key == "backspace" else current + key)
        label = (f"Filter: {escape(self.picker_filters[kind])}  ·  Backspace edits · Esc clears"
                 if self.picker_filters[kind] else "Hover and type to filter · Backspace edits · Esc clears")
        self.query_one(f"#{kind}-filter", Static).update(label)
        (self.refresh_engines if kind == "engine" else self.refresh_models)()

    def remember(self) -> None:
        if self.loading:
            return
        self.state = {
            "engines": self.selected("#engine-list"), "models": self.selected("#model-list"),
            "suite_id": self.value("suite-id"),
            "check_updates": self.query_one("#check-updates", Checkbox).value,
            "engine_mode": self.mode["engine"], "model_mode": self.mode["model"],
        }
        save_state(self.state)
        self.update_summary()

    def update_summary(self) -> None:
        self.query_one("#suite-summary", Static).update(
            f"Engines: {len(self.selected('#engine-list'))} selected\n"
            f"Models: {len(self.selected('#model-list'))} selected\n"
            f"Upstream updates: {'check' if self.query_one('#check-updates', Checkbox).value else 'skip'}"
        )

    def refresh_engines(self, editor_id: str | None = None) -> None:
        previous = set(self.selected("#engine-list"))
        self.engines = list_engines()
        previous.intersection_update(x["id"] for x in self.engines)
        self.selection_cache["engine"] = previous
        query = self.picker_filters["engine"].casefold()
        self.query_one("#engine-list", SelectionList).set_options([
            (f"{x['label']}  ·  {x['type']}", x["id"], x["id"] in previous) for x in self.engines
            if query in f"{x['label']} {x['id']} {x['type']} {x['locator']}".casefold()
        ])
        if editor_id:
            self.edit_engine_id = editor_id
            self.load_engine(editor_id)
        self.update_summary()

    def refresh_models(self, editor_id: str | None = None) -> None:
        previous = set(self.selected("#model-list"))
        self.models = list_models()
        previous.intersection_update(x["id"] for x in self.models)
        self.selection_cache["model"] = previous
        query = self.picker_filters["model"].casefold()
        picker = self.query_one("#model-list", SelectionList)
        picker.set_options([
            (x["label"], x["id"], x["id"] in previous) for x in self.models
            if query in f"{x['label']} {x['id']} {x['artifact']} {x['family']}".casefold()
        ])
        picker.display = bool(self.models)
        self.query_one("#model-empty", Static).display = not self.models
        if editor_id:
            self.edit_model_id = editor_id
            self.load_model(editor_id)
        self.update_summary()

    def value(self, ident: str) -> str:
        return self.query_one(f"#{ident}", Input).value.strip()

    def fill(self, values: dict[str, str]) -> None:
        for ident, value in values.items():
            self.query_one(f"#{ident}", Input).value = value

    def load_engine(self, ident: str) -> None:
        item = next((x for x in self.engines if x["id"] == ident), None)
        if item:
            self.query_one("#engine-type", Select).value = item["type"]
            self.fill({"engine-label": item["label"], "engine-locator": item["locator"],
                       "engine-ref": item["ref_hint"], "engine-notes": item["notes"]})

    def load_model(self, ident: str) -> None:
        item = next((x for x in self.models if x["id"] == ident), None)
        if item:
            self.fill({
                "model-label": item["label"], "model-artifact": item["artifact"],
                "model-family": item["family"], "model-context": str(item["context"] or ""),
                "model-engines": ", ".join(item["engine_ids"]), "model-notes": item["notes"],
            })

    def on_select_changed(self, event: Select.Changed) -> None:
        if self.loading:
            return
        ident = event.select.id
        if ident == "engine-type" and isinstance(event.value, str):
            self.query_one("#locator-label", Label).update(LOCATOR_LABELS[event.value])

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        self.pending_delete = None
        picker_id = event.selection_list.id
        if picker_id in {"engine-list", "model-list"}:
            kind = picker_id.split("-")[0]
            picker = event.selection_list
            visible = {option.value for option in picker.options}
            self.selection_cache[kind] = (self.selection_cache[kind] - visible) | set(picker.selected)
        self.remember()

    def on_checkbox_changed(self, _event: Checkbox.Changed) -> None:
        self.update_modes()
        self.remember()

    def update_modes(self) -> None:
        for kind in ("engine", "model"):
            agent = self.mode[kind] == "agent"
            self.query_one(f"#{kind}-agent").display = agent
            self.query_one(f"#{kind}-manual").display = not agent
            self.query_one(f"#{kind}-mode", Button).label = (
                "Switch to manual setup" if agent else "Switch to agent setup"
            )

    def refresh_request(self, kind: str) -> None:
        request = latest_request(kind)
        status = self.query_one(f"#{kind}-agent-status", Static)
        if request:
            color = {"pending": "cyan", "needs_input": "yellow", "ready": "green", "confirmed": "green"}[request["status"]]
            status.update(f"[{color}]{request['status']}[/{color}]  ·  {escape(request['message'] or request['prompt'])}")
        else:
            status.update("Describe what you want. The agent will install it or ask a question.")
        ask = self.query_one(f"#{kind}-ask", Button)
        ask.label = ("Answer & retry" if request and request["status"] == "needs_input"
                     else "Retry agent" if request and request["status"] == "pending" and request["id"] not in self.active_requests
                     else "Ask agent")
        ask.disabled = bool(request and (request["status"] == "ready" or request["id"] in self.active_requests))
        confirm = self.query_one(f"#{kind}-confirm", Button)
        confirm.display = bool(request and request["status"] == "ready")
        confirm.disabled = bool(request and request["id"] in self.active_requests)

    def poll_requests(self) -> None:
        for kind in ("engine", "model"):
            request = latest_request(kind)
            if not request or request["status"] != "pending":
                continue
            message = completion_signal(request["id"])
            if message is None:
                continue
            try:
                resolve_request(request["id"], "ready", message, request_results(request["id"]))
            except (ValueError, OSError) as exc:
                resolve_request(request["id"], "needs_input", f"Completion rejected: {exc}")
            self.active_requests.discard(request["id"])
            (self.refresh_engines if kind == "engine" else self.refresh_models)()
            self.message(f"{kind.title()} request {request['id']}: {get_request(request['id'])['status']}")
        self.refresh_request("engine")
        self.refresh_request("model")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "suite-id":
            self.remember()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = event.button.id
        try:
            if action == "engine-new":
                self.pending_delete = None
                self.edit_engine_id = None
                self.query_one("#engine-type", Select).value = "git"
                self.fill({f"engine-{x}": "" for x in ("label", "locator", "ref", "notes")})
            elif action == "model-new":
                self.pending_delete = None
                self.edit_model_id = None
                self.fill({f"model-{x}": "" for x in ("label", "artifact", "family", "context", "engines", "notes")})
            elif action in {"engine-edit", "model-edit"}:
                self.pending_delete = None
                kind = action.split("-")[0]
                selected = self.selected(f"#{kind}-list")
                if len(selected) != 1:
                    raise ValueError("Select exactly one item to edit")
                setattr(self, f"edit_{kind}_id", selected[0])
                (self.load_engine if kind == "engine" else self.load_model)(selected[0])
                self.message(f"Editing {kind} {selected[0]}")
            elif action == "engine-save":
                self.save_engine()
            elif action == "model-save":
                self.save_model()
            elif action in {"engine-remove", "model-remove"}:
                self.remove_item("engine" if action == "engine-remove" else "model")
            elif action in {"engine-mode", "model-mode"}:
                kind = action.split("-")[0]
                self.mode[kind] = "manual" if self.mode[kind] == "agent" else "agent"
                self.update_modes()
                self.remember()
            elif action and action.endswith(("-ask", "-confirm")):
                kind, request_action = action.split("-")
                self.handle_request(kind, request_action)
            elif action in {"prepare", "run"}:
                self.launch_agent(action)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            self.message(f"[red]{exc}[/red]")
            self.notify(str(exc), severity="error")

    def save_engine(self) -> None:
        kind = self.query_one("#engine-type", Select).value
        ident = save_engine({
            "id": self.edit_engine_id,
            "label": self.value("engine-label"), "type": kind,
            "locator": self.value("engine-locator"), "ref_hint": self.value("engine-ref"),
            "notes": self.value("engine-notes"),
        })
        self.refresh_engines(ident)
        self.message(f"Saved engine {ident}")

    def save_model(self) -> None:
        ident = save_model({
            "id": self.edit_model_id,
            "label": self.value("model-label"), "artifact": self.value("model-artifact"),
            "family": self.value("model-family"), "context": self.value("model-context"),
            "engine_ids": [x.strip() for x in self.value("model-engines").split(",") if x.strip()],
            "notes": self.value("model-notes"),
        })
        self.refresh_models(ident)
        self.message(f"Saved model {ident}")

    def remove_item(self, kind: str) -> None:
        selected = self.selected(f"#{kind}-list")
        if len(selected) != 1:
            raise ValueError(f"Select exactly one {kind} to remove")
        ident = selected[0]
        if kind == "engine" and next(x for x in self.engines if x["id"] == ident)["built_in"]:
            raise ValueError("Built-in engines are edited in manifests/sources.json")
        if self.pending_delete != (kind, ident):
            self.pending_delete = (kind, ident)
            self.message(f"Press Remove again to delete {kind} {ident}")
            return
        self.pending_delete = None
        (remove_engine if kind == "engine" else remove_model)(ident)
        self.state[f"{kind}s"] = [x for x in self.state.get(f"{kind}s", []) if x != ident]
        (self.refresh_engines if kind == "engine" else self.refresh_models)()
        setattr(self, f"edit_{kind}_id", None)
        self.remember()
        self.message(f"Removed {kind} {ident}")

    def handle_request(self, kind: str, action: str) -> None:
        request = latest_request(kind)
        if action == "confirm":
            if not request:
                raise ValueError("No agent result to confirm")
            ids = confirm_request(request["id"])
            removed_ids = {row["item_id"] for row in request_removals(request["id"])}
            self.selection_cache[kind].difference_update(removed_ids)
            picker = self.query_one(f"#{kind}-list", SelectionList)
            for removed_id in removed_ids:
                picker.deselect(removed_id)
            (self.refresh_engines if kind == "engine" else self.refresh_models)()
            for ident in ids:
                picker.select(ident)
            self.remember()
            self.refresh_request(kind)
            removed = len(request_removals(request["id"]))
            self.message(f"Confirmed {len(ids)} {kind} setup(s) and {removed} removal(s)")
            return
        if shutil.which("codex") is None:
            raise ValueError("Codex CLI is not installed or not on PATH")
        prompt_text = self.value(f"{kind}-request")
        if request and request["status"] == "needs_input":
            answer_request(request["id"], prompt_text)
            ident = request["id"]
        elif request and request["status"] == "pending":
            ident = request["id"]
        else:
            ident = create_request(kind, prompt_text)
        if ident in self.active_requests:
            raise ValueError("This agent is already running")
        self.query_one(f"#{kind}-request", Input).value = ""
        response_instruction = (
            "In this interactive Codex terminal, ask the user directly if clarification is needed. "
            "The program polls your finish-request signal and validates the recorded changes; "
            "do not change request status yourself. "
            if self.embedded_terminal_available() else
            "Return final JSON matching manifests/setup-response.schema.json: status ready with every "
            "saved result ID and a concise verification message, or status needs_input with specific "
            "questions and an empty result_ids array. The program validates and stores that response; "
            "do not change request status yourself. "
        )
        prompt = (
            f"Handle local benchmark {kind} setup request {ident}. Read AGENTS.md and "
            f"'uv run scripts/catalog_cli.py show-request {ident}'. The user's request may "
            "name several items. List catalog entries first. If an item is already installed, verify it "
            f"and use catalog_cli.py use-existing {ident} ITEM_ID; do not reinstall. "
            f"To register a local install use add-{kind} --request-id {ident}. "
            f"To update a saved item use update-{kind} ITEM_ID --request-id {ident}; "
            f"to remove one use remove-{kind} ITEM_ID --request-id {ident}. "
            f"After every requested item is handled, run catalog_cli.py finish-request {ident} "
            "--message 'Concise verification summary'. The TUI polls and validates this signal while "
            "your terminal remains open. "
            "Only delete files when the user's request specifically asks to uninstall them, "
            "using --delete-install --confirm-path with the exact saved path. "
            "Find authoritative sources; do not guess ambiguous names. Verify identities, local paths, "
            "and versions before recording success. "
            "Check every command exit status. " + response_instruction +
            "Do not start benchmark measurements."
        )
        self.active_requests.add(ident)
        self.refresh_request(kind)
        self.run_worker(self.start_agent_tab(kind, ident, prompt), name=f"setup-{ident}")

    async def start_agent_tab(self, kind: str, ident: str, prompt: str) -> None:
        pane_id = f"agent-{ident}"
        log_id = f"log-{ident}"
        tabs = self.query_one("#agent-tabs", TabbedContent)
        if self.embedded_terminal_available():
            terminal_id = f"terminal-{ident}"
            if self.query(f"#{pane_id}"):
                await tabs.remove_pane(pane_id)
            self.terminals[terminal_id] = ("setup", kind, ident)
            await tabs.add_pane(TabPane(
                f"{kind}: {ident[-8:]}",
                Terminal(command=["codex", "--no-daemon", "-C", str(ROOT), prompt], id=terminal_id),
                id=pane_id,
            ))
            tabs.active = pane_id
            self.query_one(f"#{terminal_id}").focus()
            self.message(f"Interactive Codex started for {kind} {ident}; Ctrl+G leaves its pane")
            return
        if not self.query(f"#{pane_id}"):
            await tabs.add_pane(TabPane(
                f"{kind}: {ident[-8:]}",
                RichLog(id=log_id, highlight=True, markup=True, max_lines=500, wrap=True),
                id=pane_id,
            ))
        tabs.active = pane_id
        self.append_agent_log(log_id, "[cyan]Starting Codex agent…[/cyan]")
        self.run_setup_agent(kind, ident, prompt, log_id)

    def append_agent_log(self, log_id: str, value: str) -> None:
        self.query_one(f"#{log_id}", RichLog).write(value)

    @staticmethod
    def format_agent_event(line: str) -> str | None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return f"[red]CLI[/red] {escape(line.strip()[:500])}" if line.strip() else None
        if not isinstance(event, dict):
            return None
        event_type = event.get("type", "")
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        item_type = item.get("type", "")
        if event_type == "item.started" and item_type == "command_execution":
            command = str(item.get("command", ""))
            try:
                parts = shlex.split(command)
                if "-lc" in parts:
                    command = parts[parts.index("-lc") + 1]
            except (ValueError, IndexError):
                pass
            command = command.replace(str(Path.home()), "~")
            return f"[cyan]Running[/cyan] {escape(command[:150])}{'…' if len(command) > 150 else ''}"
        if event_type == "item.completed" and item_type == "command_execution":
            output = str(item.get("aggregated_output") or "").strip()
            code = item.get("exit_code")
            if code not in (None, 0):
                detail = output.splitlines()[-1][:180] if output else "No output"
                return f"[red]Command failed ({code})[/red] {escape(detail)}"
            if output and len(output) <= 240 and len(output.splitlines()) <= 2:
                return f"[dim]↳ {escape(output)}[/dim]"
            return None
        if event_type == "item.completed" and item_type == "agent_message":
            message = str(item.get("text") or "").strip()
            if not message:
                return None
            try:
                result = json.loads(message)
                if isinstance(result, dict) and result.get("status") in {"ready", "needs_input"}:
                    color = "green" if result["status"] == "ready" else "yellow"
                    return f"[{color}]{result['status']}[/{color}] {escape(str(result.get('message', ''))[:500])}"
            except json.JSONDecodeError:
                pass
            return f"[bold]Agent[/bold] {escape(message[:1200])}"
        if event_type == "turn.completed":
            return "[green]Agent finished[/green]"
        if "error" in event_type or "failed" in event_type:
            detail = event.get("message") or event.get("error") or event_type
            return f"[red]Error[/red] {escape(str(detail)[:500])}"
        return None

    @work(thread=True)
    def run_setup_agent(self, kind: str, ident: str, prompt: str, log_id: str) -> None:
        with tempfile.TemporaryDirectory(prefix="benchmark-agent-") as temp:
            response_file = Path(temp) / "response.json"
            command = [
                "codex", "exec", "--json", "-C", str(ROOT),
                "--output-schema", str(ROOT / "manifests/setup-response.schema.json"),
                "--output-last-message", str(response_file), prompt,
            ]
            try:
                process = subprocess.Popen(
                    command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                )
                assert process.stdout is not None
                for line in process.stdout:
                    formatted = self.format_agent_event(line)
                    if formatted:
                        self.call_from_thread(self.append_agent_log, log_id, formatted)
                code = process.wait()
                response = json.loads(response_file.read_text()) if code == 0 and response_file.exists() else None
                self.call_from_thread(self.finish_setup_agent, kind, ident, log_id, code, response)
            except (OSError, json.JSONDecodeError) as exc:
                self.call_from_thread(self.finish_setup_agent, kind, ident, log_id, 1, {"error": str(exc)})

    def finish_setup_agent(self, kind: str, ident: str, log_id: str,
                           code: int, response: dict | None) -> None:
        if get_request(ident)["status"] in {"ready", "confirmed"}:
            self.active_requests.discard(ident)
            self.refresh_request(kind)
            return
        try:
            if code == 0 and isinstance(response, dict):
                resolve_request(
                    ident, response.get("status", ""), response.get("message", ""),
                    response.get("result_ids", []),
                )
            else:
                detail = response.get("error") if isinstance(response, dict) else f"exit status {code}"
                resolve_request(ident, "needs_input",
                                f"Agent stopped without a valid result ({detail}). Review its output and enter a correction or retry.")
        except (ValueError, OSError) as exc:
            resolve_request(ident, "needs_input",
                            f"Agent result was rejected: {exc}. Review its output and provide corrected details.")
        self.active_requests.discard(ident)
        (self.refresh_engines if kind == "engine" else self.refresh_models)()
        self.refresh_request(kind)
        status = get_request(ident)["status"]
        if code:
            self.append_agent_log(log_id, f"[red]Agent process failed with exit status {code}[/red]")
        color = "green" if status == "ready" else "yellow"
        self.append_agent_log(log_id, f"[{color}]Request {status}[/{color}]")
        self.message(f"{kind.title()} request {ident}: {status}")

    def launch_agent(self, stage: str) -> None:
        self.remember()
        suite_id = self.value("suite-id")
        engines = self.selected("#engine-list")
        models = self.selected("#model-list")
        if not suite_id or not engines or not models:
            raise ValueError("Enter a suite name and select at least one engine and model")
        if shutil.which("codex") is None:
            raise ValueError("Codex CLI is not installed or not on PATH")
        check_updates = self.query_one("#check-updates", Checkbox).value if stage == "prepare" else False
        prompt = make_prompt(stage, suite_id, engines, models, check_updates)
        self.run_worker(self.start_suite_tab(stage, suite_id, engines, models, check_updates, prompt),
                        name=f"{stage}-{suite_id}")

    async def start_suite_tab(self, stage: str, suite_id: str, engines: list[str],
                              models: list[str], check_updates: bool, prompt: str) -> None:
        pane_id = f"suite-agent-{stage}-{suite_id}"
        log_id = f"suite-log-{stage}-{suite_id}"
        tabs = self.query_one("#agent-tabs", TabbedContent)
        if self.embedded_terminal_available():
            try:
                await asyncio.to_thread(self.preflight_suite, stage, suite_id, engines, models, check_updates)
            except (ValueError, OSError) as exc:
                self.message(f"{stage} failed: {exc}")
                return
            terminal_id = f"suite-terminal-{len(self.terminals)}"
            self.terminals[terminal_id] = ("suite", stage, suite_id)
            if self.query(f"#{pane_id}"):
                await tabs.remove_pane(pane_id)
            await tabs.add_pane(TabPane(
                f"{stage}: {suite_id}",
                Terminal(command=["codex", "--no-daemon", "-C", str(ROOT), prompt], id=terminal_id),
                id=pane_id,
            ))
            tabs.active = pane_id
            self.query_one(f"#{terminal_id}").focus()
            self.message(f"Interactive Codex started for {stage} {suite_id}; Ctrl+G leaves its pane")
            return
        if not self.query(f"#{pane_id}"):
            await tabs.add_pane(TabPane(
                f"{stage}: {suite_id}",
                RichLog(id=log_id, highlight=True, markup=True, max_lines=500, wrap=True),
                id=pane_id,
            ))
        tabs.active = pane_id
        self.append_agent_log(log_id, f"[cyan]Starting {stage}…[/cyan]")
        self.run_suite_agent(stage, suite_id, engines, models, check_updates, prompt, log_id)

    @staticmethod
    def preflight_suite(stage: str, suite_id: str, engines: list[str], models: list[str],
                        check_updates: bool) -> None:
        if stage == "prepare":
            create_suite(suite_id, engines, models, check_updates)
        else:
            frozen = show_suite(suite_id)
            if frozen["suite"]["status"] != "frozen":
                raise ValueError("Suite is not frozen; prepare it first")
            if set(engines) != {x["engine_id"] for x in frozen["engines"]} or set(models) != {x["model_id"] for x in frozen["models"]}:
                raise ValueError("Current selections differ from the frozen suite")
            validate_suite(suite_id)

    def on_terminal_process_exited(self, event: Terminal.ProcessExited) -> None:
        terminal_id = getattr(event._sender, "id", None)
        info = self.terminals.pop(terminal_id, None)
        if not info:
            return
        if info[0] == "suite":
            _, stage, suite_id = info
            if stage == "prepare":
                status = show_suite(suite_id)["suite"]["status"]
                self.message(f"Suite {suite_id}: {status} (agent exit {event.exit_code})")
            else:
                self.message(f"Run agent exited with status {event.exit_code}; review its results")
            return
        _, kind, ident = info
        if get_request(ident)["status"] in {"ready", "confirmed"}:
            self.active_requests.discard(ident)
            self.refresh_request(kind)
            return
        ids = request_results(ident)
        removals = request_removals(ident)
        try:
            if event.exit_code == 0 and (ids or removals):
                resolve_request(ident, "ready", f"Verified {len(ids)} saved {kind} setup(s) and {len(removals)} removal(s)", ids)
            else:
                reason = "No results were recorded" if not ids and not removals else f"agent exit status {event.exit_code}"
                resolve_request(ident, "needs_input", f"{reason}. Review the terminal and retry or provide a correction.")
        except (ValueError, OSError) as exc:
            resolve_request(ident, "needs_input", f"Agent result was rejected: {exc}. Correct it and retry.")
        self.active_requests.discard(ident)
        (self.refresh_engines if kind == "engine" else self.refresh_models)()
        self.refresh_request(kind)
        self.message(f"{kind.title()} request {ident}: {get_request(ident)['status']}")

    @work(thread=True)
    def run_suite_agent(self, stage: str, suite_id: str, engines: list[str], models: list[str],
                        check_updates: bool, prompt: str, log_id: str) -> None:
        try:
            self.preflight_suite(stage, suite_id, engines, models, check_updates)
            process = subprocess.Popen(
                ["codex", "exec", "--json", "-C", str(ROOT), prompt],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                formatted = self.format_agent_event(line)
                if formatted:
                    self.call_from_thread(self.append_agent_log, log_id, formatted)
            code = process.wait()
            self.call_from_thread(self.finish_suite_agent, stage, suite_id, log_id, code)
        except (ValueError, OSError) as exc:
            self.call_from_thread(self.append_agent_log, log_id, f"[red]{escape(str(exc))}[/red]")
            self.call_from_thread(self.message, f"{stage} failed: {exc}")

    def finish_suite_agent(self, stage: str, suite_id: str, log_id: str, code: int) -> None:
        if code:
            self.append_agent_log(log_id, f"[red]Agent process failed with exit status {code}[/red]")
        if stage == "prepare":
            status = show_suite(suite_id)["suite"]["status"]
            color = "green" if status == "frozen" else "yellow"
            self.append_agent_log(log_id, f"[{color}]Suite {status}[/{color}]")
            self.message(f"Suite {suite_id}: {status}")
        else:
            color = "cyan" if code == 0 else "red"
            self.append_agent_log(log_id, f"[{color}]Run agent exited with status {code}; review its results[/{color}]")
            self.message(f"Run agent exited with status {code}")


def main() -> None:
    try:
        BenchmarkApp().run()
    except (ValueError, OSError) as exc:
        print(f"Cannot start benchmark TUI: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
