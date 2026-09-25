#!/usr/bin/env python3
"""Small terminal UI for choosing engines and models before agent preparation."""

import asyncio
import json
import os
import shlex
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from rich.markup import escape
from bittty import constants
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import (
    Button, Checkbox, Footer, Header, Input, Label, RichLog, Select, TextArea,
    OptionList, SelectionList, Static, TabbedContent, TabPane, Tabs,
)
from textual_tty import Terminal

from source_manifest import ROOT
from run_store import clone_setup, create_run, delete_setup, list_setups, save_setup, show_setup
from results_store import list_results, pull_findings, show_result
from start_codex import make_prompt
from suite_store import create_suite, delete_suite, list_suites, preparation_signal, show_suite, validate_suite
from tui_data import (
    answer_request, completion_signal, confirm_request, create_request, dismiss_requests, get_request, latest_request,
    list_engines, list_models, load_state, migrate_old_files, remove_engine,
    remove_model, request_removals, request_results, resolve_request, save_engine, save_model, save_state,
    update_builtin_engine,
)

TYPES = ("git", "package", "container", "remote", "local")
TMUX_CONFIG = Path(__file__).with_name("tmux-agent.conf")
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
            if event.key == "escape":
                self.app.action_clear_edit()
        elif event.character and event.character.isprintable() and not event.character.isspace():
            self.app.change_picker_filter(self.id, event.character)
        else:
            return
        event.prevent_default()
        event.stop()

    def _on_click(self, event) -> None:
        if event.button == 3:
            index = event.style.meta.get("option") if event.style else None
            if index is not None:
                self.highlighted = index
                self.app.open_manual_editor(self.id, self.get_option_at_index(index).value)
            event.stop()
            event.prevent_default()
            return


class CodexTerminal(Terminal):
    """Forward wheel events to tmux, or use Codex's transcript without tmux."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.transcript_open = False
        self.tmux_mode = False

    def toggle_transcript(self) -> None:
        self.board.display.input_key("t", constants.KEY_MOD_CTRL)
        self.transcript_open = not self.transcript_open

    def on_key(self, event) -> None:
        if event.key == "ctrl+t":
            self.transcript_open = not self.transcript_open
        elif self.transcript_open and event.key in {"escape", "q"}:
            self.transcript_open = False
        super().on_key(event)

    def on_mouse_scroll_up(self, event) -> None:
        if self.tmux_mode:
            self.board.host.write(f"\x1b[<64;{event.offset.x + 1};{event.offset.y + 1}M")
            event.stop()
            return
        if not self.transcript_open:
            self.toggle_transcript()
        for _ in range(3):
            self.board.display.input_key("up")
        event.stop()

    def on_mouse_scroll_down(self, event) -> None:
        if self.tmux_mode:
            self.board.host.write(f"\x1b[<65;{event.offset.x + 1};{event.offset.y + 1}M")
            event.stop()
            return
        if self.transcript_open:
            for _ in range(3):
                self.board.display.input_key("down")
            event.stop()
        else:
            super().on_mouse_scroll_down(event)


def embedded_codex_command(prompt: str) -> tuple[list[str], str | None]:
    codex = ["codex", "--no-daemon", "--no-alt-screen", "-C", str(ROOT), prompt]
    tmux = shutil.which("tmux")
    if tmux:
        socket = f"llmbench-{os.getpid()}-{uuid.uuid4().hex[:12]}"
        return ([tmux, "-L", socket, "-f", str(TMUX_CONFIG),
                 "new-session", "-s", "agent", "--", shlex.join(codex)], socket)
    return codex, None


def make_build_prompt(engine: dict) -> str:
    """Give one agent ownership of one selected Git engine's build."""
    return (
        f"Build the selected Git engine {engine['id']!r} ({engine['locator']}). "
        f"The catalog records revision {engine['revision'] or 'not yet pinned'} and "
        f"installed path {engine['installed_path'] or 'not yet recorded'}. "
        "Read AGENTS.md, the matching guide in guides/, and the engine's own build instructions. "
        "Use the catalog's installed checkout if present; otherwise install the recorded source "
        "at its pinned revision. For a custom source without an exact revision, resolve its revision "
        "and report it before building. Do not modify another engine's checkout or update a pin "
        "silently. Verify the checkout HEAD and working tree before changing anything. "
        "Build in this engine's own checkout using the backend appropriate to this machine. "
        "Avoid exhausting the machine with unrestricted parallel compilation. "
        "Check every command exit status and verify the built executable or service with its "
        "version or help command. Do not load models, run benchmarks, or publish results. "
        "Report the source revision, build command, build output path, verification command, "
        "and any failure or missing prerequisite. If a build cannot be verified, say so explicitly."
    )


class BenchmarkApp(App[None]):
    TITLE = "LLM Benchmarks"
    SUB_TITLE = "engines · models · suite"
    BINDINGS = [("q", "quit", "Quit"), ("escape", "clear_edit", "Clear edit"),
                Binding("ctrl+g", "focus_agent_tabs", "Leave agent", priority=True)]
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
    #suite-stage-status { height: 1; color: $text-muted; }
    #suite-summary { margin: 1 0; }
    .agent-panel { height: 1fr; }
    Terminal { height: 1fr; }
    CodexTerminal { height: 1fr; }
    #suite-list { height: 9; border: round $primary; margin-bottom: 1; }
    #run-setup-list { height: 7; border: round $primary; margin-bottom: 1; }
    #run-description { height: 6; border: round $primary; margin-bottom: 1; }
    #suite-scroll { height: 1fr; }
    #suite-detail { min-height: 3; color: $text-muted; }
    .request-status { margin: 1 0; }
    .mode-button { dock: bottom; height: 3; margin: 1 0 0 0; }
    #agent-tabs { height: 1fr; }
    #result-list { height: 11; border: round $primary; margin-bottom: 1; }
    #result-detail { min-height: 3; margin-bottom: 1; }
    #result-findings { height: 1fr; border: round $primary; }
    """

    def __init__(self) -> None:
        super().__init__()
        migrate_old_files()
        self.engines = list_engines()
        self.models = list_models()
        self.state = load_state()
        self.loading = True
        self.pending_delete: tuple[str, str] | None = None
        self.pending_suite_delete: str | None = None
        self.pending_run_setup_delete: str | None = None
        self.run_setup_id: str | None = self.state.get("run_setup_id")
        self.active_run_machine = False
        self.edit_engine_id: str | None = None
        self.edit_model_id: str | None = None
        self.mode = {
            "engine": self.state.get("engine_mode", "agent"),
            "model": self.state.get("model_mode", "agent"),
        }
        self.active_requests: set[str] = set()
        self.active_builds: set[str] = set()
        self.terminals: dict[str, tuple[str, ...]] = {}
        self.result_rows: list[dict] = []
        self.tmux_sockets: dict[str, tuple[str, str]] = {}
        self.tmux_missing: dict[str, int] = {}
        self.announced_preparations: set[str] = set()
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

    def cleanup_tmux(self, terminal_id: str) -> None:
        self.tmux_missing.pop(terminal_id, None)
        session = self.tmux_sockets.pop(terminal_id, None)
        if session:
            tmux, socket = session
            try:
                subprocess.run([tmux, "-L", socket, "kill-server"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=3, check=False)
                live = subprocess.run([tmux, "-L", socket, "has-session"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      timeout=3, check=False).returncode == 0
                if not live and socket.startswith("llmbench-") and hasattr(os, "getuid"):
                    socket_path = (Path(os.environ.get("TMUX_TMPDIR") or tempfile.gettempdir()) /
                                   f"tmux-{os.getuid()}" / socket)
                    try:
                        info = socket_path.lstat()
                        if stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid():
                            socket_path.unlink()
                    except FileNotFoundError:
                        pass
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.log.error(f"Could not close private tmux server {socket}: {exc}")

    @staticmethod
    def tmux_pane_state(tmux: str, socket: str) -> tuple[str, int | None]:
        try:
            result = subprocess.run(
                [tmux, "-L", socket, "list-panes", "-t", "agent", "-F", "#{pane_dead} #{pane_dead_status}"],
                capture_output=True, text=True, timeout=1, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "missing", None
        if result.returncode:
            return "missing", None
        fields = result.stdout.strip().split()
        if fields and fields[0] == "1":
            try:
                return "dead", int(fields[1])
            except (IndexError, ValueError):
                return "dead", 1
        return "running", None

    def on_unmount(self) -> None:
        for info in self.terminals.values():
            if info[0] == "setup":
                try:
                    request = get_request(info[2])
                    if request["status"] == "pending":
                        signal = completion_signal(info[2])
                        if signal:
                            try:
                                resolve_request(info[2], "ready", signal, request_results(info[2]))
                            except (ValueError, OSError) as exc:
                                resolve_request(info[2], "failed", f"Completion rejected during shutdown: {exc}")
                        else:
                            resolve_request(info[2], "canceled", "TUI closed before Codex completed setup.")
                except (ValueError, OSError) as exc:
                    self.log.error(f"Could not finalize setup request {info[2]}: {exc}")
        for terminal_id in list(self.tmux_sockets):
            self.cleanup_tmux(terminal_id)

    def action_focus_agent_tabs(self) -> None:
        self.query_one("#agent-tabs Tabs", Tabs).focus()

    def action_clear_edit(self) -> None:
        for kind in ("engine", "model"):
            if getattr(self, f"edit_{kind}_id") is not None:
                self.clear_manual_editor(kind)

    def clear_manual_editor(self, kind: str) -> None:
        setattr(self, f"edit_{kind}_id", None)
        if kind == "engine":
            self.query_one("#engine-type", Select).disabled = False
            self.query_one("#engine-type", Select).value = "git"
            for field in ("label", "locator", "notes"):
                self.query_one(f"#engine-{field}", Input).disabled = False
            self.fill({f"engine-{field}": "" for field in
                       ("label", "locator", "ref", "revision", "installed-path", "notes")})
        else:
            self.fill({f"model-{field}": "" for field in
                       ("label", "artifact", "family", "context", "engines", "notes")})
        self.query_one(f"#{kind}-editor-title", Label).update(f"Add {'an engine' if kind == 'engine' else 'a model'}")
        button = self.query_one(f"#{kind}-save", Button)
        button.label = f"Add {kind}"
        button.disabled = False
        self.pending_delete = None

    def open_manual_editor(self, picker_id: str | None, ident: str, switch_mode: bool = True) -> None:
        if picker_id not in {"engine-list", "model-list"}:
            return
        kind = picker_id.split("-")[0]
        items = self.engines if kind == "engine" else self.models
        item = next((row for row in items if row["id"] == ident), None)
        if item is None:
            raise ValueError(f"Unknown {kind} {ident}")
        if switch_mode:
            self.mode[kind] = "manual"
            self.update_modes()
        setattr(self, f"edit_{kind}_id", ident)
        (self.load_engine if kind == "engine" else self.load_model)(ident)
        self.query_one(f"#{kind}-editor-title", Label).update(f"Editing {kind}: {item['label']}")
        save_button = self.query_one(f"#{kind}-save", Button)
        save_button.label = f"Update {kind}"
        if kind == "engine":
            built_in = item["built_in"]
            self.query_one("#engine-type", Select).disabled = built_in
            for field in ("label", "locator", "notes"):
                self.query_one(f"#engine-{field}", Input).disabled = built_in
            save_button.disabled = built_in and item["type"] != "git"
        self.pending_delete = None
        self.remember()
        self.message(f"Editing {kind} {ident}; Escape or New clears the editor")

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="engines", id="main-tabs"):
            with TabPane("Engines", id="engines"):
                yield Label("Choose engines (Space toggles selection)", classes="section-title")
                yield Static("Hover and type to filter · Backspace edits · Esc clears", id="engine-filter", classes="picker-filter")
                yield SearchableSelectionList(id="engine-list", classes="picker")
                yield Button("Build selected", id="engine-build", variant="primary")
                with VerticalScroll(id="engine-agent", classes="agent-panel"):
                    yield Label("Tell the agent what to install", classes="section-title")
                    yield Input(id="engine-request", placeholder="Install theTom's fork from GitHub")
                    with Horizontal(classes="buttons"):
                        yield Button("Ask agent", id="engine-ask", variant="primary")
                        yield Button("Confirm result", id="engine-confirm", variant="success")
                        yield Button("Clear status", id="engine-clear")
                    yield Static(id="engine-agent-status", classes="request-status")
                with VerticalScroll(id="engine-manual", classes="form"):
                    yield Label("Add an engine", id="engine-editor-title", classes="section-title")
                    yield Label("Name (optional)", classes="field-label")
                    yield Input(id="engine-label", placeholder="e.g. My fast engine")
                    yield Label("Type", classes="field-label")
                    yield Select([(x.title(), x) for x in TYPES], id="engine-type", value="git", allow_blank=False)
                    yield Label("Git URL", id="locator-label", classes="field-label")
                    yield Input(id="engine-locator", placeholder="https://example.org/engine.git")
                    yield Label("Branch or reference (optional)", classes="field-label")
                    yield Input(id="engine-ref", placeholder="leave empty to let the agent determine it")
                    yield Label("Installed revision (optional)", classes="field-label")
                    yield Input(id="engine-revision", placeholder="exact commit or version")
                    yield Label("Installed path (optional)", classes="field-label")
                    yield Input(id="engine-installed-path", placeholder="/path/to/checkout")
                    yield Label("Notes (optional)", classes="field-label")
                    yield Input(id="engine-notes", placeholder="anything the agent should know")
                    with Horizontal(classes="buttons"):
                        yield Button("New", id="engine-new")
                        yield Button("Edit selected", id="engine-edit")
                        yield Button("Add engine", id="engine-save", variant="success")
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
                        yield Button("Clear status", id="model-clear")
                    yield Static(id="model-agent-status", classes="request-status")
                with VerticalScroll(id="model-manual", classes="form"):
                    yield Label("Add a model", id="model-editor-title", classes="section-title")
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
                        yield Button("Add model", id="model-save", variant="success")
                        yield Button("Remove", id="model-remove", variant="error")
                yield Button("Switch to manual setup", id="model-mode", classes="mode-button")
            with TabPane("Suite", id="suite"):
                with VerticalScroll(id="suite-scroll"):
                    yield Label("Prepare a suite, then run its frozen plan", classes="section-title")
                    yield Label("Saved suites", classes="field-label")
                    yield OptionList(id="suite-list")
                    with Horizontal(classes="buttons"):
                        yield Button("New", id="suite-new")
                        yield Button("Open", id="suite-open", variant="primary")
                        yield Button("Delete", id="suite-delete", variant="error")
                    yield Static("Select a suite to see its details.", id="suite-detail")
                    yield Label("Suite name", classes="field-label")
                    yield Input(id="suite-id", placeholder="e.g. september-sweep")
                    yield Checkbox("Check upstream updates during preparation", id="check-updates")
                    yield Static(id="suite-summary")
                    with Horizontal(classes="buttons"):
                        yield Button("Save draft", id="suite-create")
                        yield Button("Prepare with Codex", id="prepare", variant="primary")
                    yield Static("The agent resolves versions, hashes, tokenizer, and per-model commands. Code validates the saved plan.")
                    yield Label("Run setups", classes="section-title")
                    yield OptionList(id="run-setup-list")
                    with Horizontal(classes="buttons"):
                        yield Button("New", id="run-setup-new")
                        yield Button("Open", id="run-setup-open")
                        yield Button("Clone", id="run-setup-clone")
                        yield Button("Delete", id="run-setup-delete", variant="error")
                    yield Label("Setup name", classes="field-label")
                    yield Input(id="run-setup-name", placeholder="e.g. 8 GiB placement sweep")
                    yield Label("VRAM ceiling in GiB (optional)", classes="field-label")
                    yield Input(id="run-vram-ceiling", placeholder="e.g. 8 or 12")
                    yield Label("Run description and instructions (optional)", classes="field-label")
                    yield TextArea("", id="run-description")
                    with Horizontal(classes="buttons"):
                        yield Button("Save setup", id="run-setup-save", variant="success")
                        yield Button("Run frozen plan", id="run", variant="primary")
                    yield Static("Edit a saved setup freely. Each launch keeps an immutable copy of its instructions.")
            with TabPane("Results", id="results"):
                yield Label("Local runs", classes="section-title")
                yield OptionList(id="result-list")
                with Horizontal(classes="buttons"):
                    yield Button("Refresh runs", id="result-refresh")
                    yield Button("Pull findings", id="result-pull", variant="primary")
                    yield Button("Talk to Codex", id="result-talk", variant="success")
                yield Static("Select a run to review.", id="result-detail")
                yield Input(id="result-question", placeholder="Optional first question for Codex")
                yield RichLog(id="result-findings", highlight=True, markup=True, wrap=True)
            with TabPane("Agents", id="agents"):
                with TabbedContent(id="agent-tabs"):
                    with TabPane("Overview", id="agent-overview"):
                        yield Static("Agent output appears here while setup requests run.")
        yield Static("No suite selected", id="suite-stage-status")
        yield RichLog(id="messages", highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_engines()
        self.refresh_models()
        self.refresh_suites()
        self.query_one("#suite-id", Input).value = self.state.get("suite_id", "")
        self.refresh_run_setups()
        self.refresh_results()
        if self.run_setup_id and any(row["id"] == self.run_setup_id for row in self.run_setup_rows):
            self.open_run_setup()
        self.query_one("#check-updates", Checkbox).value = bool(self.state.get("check_updates", False))
        self.loading = False
        self.update_modes()
        self.refresh_request("engine")
        self.refresh_request("model")
        self.set_interval(1, self.poll_requests)
        self.update_summary()
        self.poll_suite_progress()
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
            "run_setup_id": self.run_setup_id,
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

    def refresh_suites(self) -> None:
        picker = self.query_one("#suite-list", OptionList)
        old = self.highlighted_suite()
        rows = list_suites()
        picker.clear_options()
        for row in rows:
            marker = "●" if row["prepared"] else "○"
            picker.add_option(f"{row['id']}  ·  {row['status']} {marker}  ·  {row['engine_count']} engines / {row['model_count']} models")
        if old:
            for index, row in enumerate(rows):
                if row["id"] == old:
                    picker.highlighted = index
                    break
        self.suite_rows = rows
        self.show_suite_detail()

    def highlighted_suite(self) -> str | None:
        picker = self.query_one("#suite-list", OptionList)
        index = picker.highlighted
        rows = getattr(self, "suite_rows", [])
        return rows[index]["id"] if index is not None and index < len(rows) else None

    def show_suite_detail(self) -> None:
        ident = self.highlighted_suite()
        row = next((x for x in getattr(self, "suite_rows", []) if x["id"] == ident), None)
        detail = self.query_one("#suite-detail", Static)
        if row is None:
            detail.update("No saved suite selected.")
            return
        detail.update(f"{escape(ident)} · {row['status']} · {row['engine_count']} engines, "
                      f"{row['model_count']} models, {row['packet_count']} packets · "
                      f"updates {'on' if row['check_updates'] else 'off'} · "
                      f"preparation {'complete' if row['prepared'] else 'pending'}")

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "suite-list":
            self.pending_suite_delete = None
            self.show_suite_detail()
        elif event.option_list.id == "run-setup-list":
            self.pending_run_setup_delete = None
        elif event.option_list.id == "result-list":
            self.show_result_detail()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "suite-list":
            self.open_suite()
        elif event.option_list.id == "run-setup-list":
            self.open_run_setup()
        elif event.option_list.id == "result-list":
            self.show_result_detail()

    def highlighted_result(self) -> str | None:
        index = self.query_one("#result-list", OptionList).highlighted
        return (self.result_rows[index]["key"] if index is not None and index < len(self.result_rows)
                else None)

    def refresh_results(self) -> None:
        selected = self.highlighted_result() if self.result_rows else None
        self.result_rows = list_results()
        picker = self.query_one("#result-list", OptionList)
        picker.clear_options()
        for row in self.result_rows:
            picker.add_option(f"{row['key']}  ·  {row['status']}")
        if self.result_rows:
            picker.highlighted = next((i for i, row in enumerate(self.result_rows)
                                       if row["key"] == selected), 0)
        self.show_result_detail()

    def show_result_detail(self) -> None:
        key = self.highlighted_result()
        detail = self.query_one("#result-detail", Static)
        if not key:
            detail.update("No local runs found yet.")
            return
        try:
            result = show_result(key)
            detail.update(f"{key}\n{result['directory']}\n"
                          f"Summary: {result['summary_file'] or 'not saved yet'} · "
                          f"Reviewed findings: {'saved' if result['findings_saved'] else 'not saved'}")
        except (ValueError, OSError) as exc:
            detail.update(f"Could not read run: {exc}")

    def show_findings(self) -> None:
        key = self.highlighted_result()
        if not key:
            raise ValueError("Select a run first")
        data = pull_findings(key)
        log = self.query_one("#result-findings", RichLog)
        log.clear()
        log.write(f"[bold cyan]{escape(key)}[/bold cyan] · {escape(data['source'])}")
        log.write(escape(data["summary"]))
        for item in data["highlights"]:
            log.write(f"[green]•[/green] {escape(item)}")
        for item in data["limitations"]:
            log.write(f"[yellow]Limit:[/yellow] {escape(item)}")
        for item in data["artifacts"]:
            log.write(f"[dim]Source: {escape(item)}[/dim]")

    async def start_results_agent(self, key: str, question: str) -> None:
        tabs = self.query_one("#agent-tabs", TabbedContent)
        active = next((ident for ident, info in self.terminals.items()
                       if info == ("results", key)), None)
        if active:
            for pane in tabs.query(TabPane):
                if pane.query(f"#{active}"):
                    tabs.active = pane.id
                    self.query_one("#main-tabs", TabbedContent).active = "agents"
                    self.query_one(f"#{active}").focus()
                    return
        prompt = (
            f"Discuss the benchmark results for {key}. Read AGENTS.md and RUNBOOK.md, then "
            f"run `uv run scripts/results_store.py show {key}` and "
            f"`uv run scripts/results_store.py pull-findings {key}`. Inspect raw evidence when needed. "
            "Be interactive and answer the user's questions. Cite paths inside this run for each finding. "
            "Distinguish observational throughput from quality-matched comparisons, and state output "
            "or token-count limits. Do not rerun benchmarks or publish anything. When the user asks "
            "you to save findings, write JSON with summary, highlights, limitations, and relative "
            "artifact paths, then submit it through `uv run scripts/results_store.py record-findings "
            f"{key} PATH_TO_JSON`; check the exit status. "
            + (f"Start by answering: {question}" if question else "Start with a concise review of this run.")
        )
        pane_id = f"result-agent-{uuid.uuid4().hex[:12]}"
        if self.embedded_terminal_available():
            terminal_id = f"result-terminal-{uuid.uuid4().hex[:12]}"
            command, socket = embedded_codex_command(prompt)
            terminal = CodexTerminal(command=command, id=terminal_id)
            terminal.tmux_mode = socket is not None
            toolbar = (Static("Mouse wheel: scroll history · q: return to Codex") if socket else
                       Button("Transcript / scroll history (Ctrl+T)", id=f"transcript-{terminal_id}"))
            self.terminals[terminal_id] = ("results", key)
            if socket:
                self.tmux_sockets[terminal_id] = (command[0], socket)
            await tabs.add_pane(TabPane(f"results: {key}", toolbar, terminal, id=pane_id))
            tabs.active = pane_id
            self.query_one("#main-tabs", TabbedContent).active = "agents"
            terminal.focus()
        else:
            log_id = f"result-log-{uuid.uuid4().hex[:12]}"
            await tabs.add_pane(TabPane(f"results: {key}",
                                        RichLog(id=log_id, highlight=True, markup=True, max_lines=500,
                                                wrap=True), id=pane_id))
            tabs.active = pane_id
            self.query_one("#main-tabs", TabbedContent).active = "agents"
            self.append_agent_log(log_id, "[yellow]Monochrome mode shows a one-shot review. Use a color terminal for interactive chat.[/yellow]")
            self.run_results_agent(key, prompt, log_id)

    @work(thread=True)
    def run_results_agent(self, key: str, prompt: str, log_id: str) -> None:
        try:
            process = subprocess.Popen(["codex", "exec", "--json", "-C", str(ROOT), prompt],
                                       cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, bufsize=1)
            assert process.stdout is not None
            for line in process.stdout:
                formatted = self.format_agent_event(line)
                if formatted:
                    self.call_from_thread(self.append_agent_log, log_id, formatted)
            self.call_from_thread(self.finish_results_agent, key, process.wait())
        except OSError as exc:
            self.call_from_thread(self.append_agent_log, log_id, f"[red]{escape(str(exc))}[/red]")
            self.call_from_thread(self.finish_results_agent, key, 1)

    def finish_results_agent(self, key: str, exit_code: int) -> None:
        self.refresh_results()
        self.message(f"Results agent for {key} exited ({exit_code}); Pull findings to refresh the review")

    def open_suite(self) -> None:
        ident = self.highlighted_suite()
        if ident is None:
            raise ValueError("Select a saved suite to open")
        data = show_suite(ident)
        for kind, key in (("engine", "engines"), ("model", "models")):
            ids = {x[f"{kind}_id"] for x in data[key]}
            known = {x["id"] for x in (self.engines if kind == "engine" else self.models)}
            if ids - known:
                raise ValueError(f"Suite {ident} references missing {kind} entries: {', '.join(sorted(ids - known))}")
            self.selection_cache[kind] = ids
            picker = self.query_one(f"#{kind}-list", SelectionList)
            picker.deselect_all()
            for item in ids:
                if any(option.value == item for option in picker.options):
                    picker.select(item)
        self.query_one("#suite-id", Input).value = ident
        self.new_run_setup()
        self.refresh_run_setups()
        self.query_one("#check-updates", Checkbox).value = bool(data["suite"]["check_updates"])
        self.remember()
        self.poll_suite_progress()
        self.message(f"Opened suite {ident}")

    def new_suite(self) -> None:
        self.query_one("#suite-id", Input).value = ""
        self.new_run_setup()
        self.refresh_run_setups()
        self.pending_suite_delete = None
        self.remember()
        self.poll_suite_progress()
        self.query_one("#suite-id", Input).focus()

    def save_suite_draft(self) -> None:
        ident = self.value("suite-id")
        create_suite(ident, self.selected("#engine-list"), self.selected("#model-list"),
                     self.query_one("#check-updates", Checkbox).value)
        self.remember()
        self.refresh_suites()
        self.poll_suite_progress()
        self.message(f"Saved draft suite {ident}")

    def remove_suite(self) -> None:
        ident = self.highlighted_suite()
        if ident is None:
            raise ValueError("Select a saved suite to delete")
        if any(info[0] == "suite" and info[2] == ident for info in self.terminals.values()):
            raise ValueError("Close the active suite agent before deleting this suite")
        if self.pending_suite_delete != ident:
            self.pending_suite_delete = ident
            self.message(f"Press Delete again to remove suite {ident} and its saved plan")
            return
        delete_suite(ident)
        self.pending_suite_delete = None
        if self.value("suite-id") == ident:
            self.new_suite()
        self.refresh_suites()
        self.message(f"Deleted suite {ident}; source files and benchmark artifacts remain")

    def refresh_run_setups(self, select_id: str | None = None) -> None:
        suite_id = self.value("suite-id")
        rows = list_setups(suite_id) if suite_id else []
        self.run_setup_rows = rows
        picker = self.query_one("#run-setup-list", OptionList)
        picker.clear_options()
        for row in rows:
            ceiling = (f"{row['vram_ceiling_gib']:g} GiB" if row["vram_ceiling_gib"] is not None
                       else "no VRAM ceiling")
            picker.add_option(f"{row['name']}  ·  {ceiling}")
        selected = select_id or self.run_setup_id
        for index, row in enumerate(rows):
            if row["id"] == selected:
                picker.highlighted = index
                return

    def highlighted_run_setup(self) -> str | None:
        index = self.query_one("#run-setup-list", OptionList).highlighted
        rows = getattr(self, "run_setup_rows", [])
        return rows[index]["id"] if index is not None and index < len(rows) else None

    def new_run_setup(self) -> None:
        self.run_setup_id = None
        self.pending_run_setup_delete = None
        self.query_one("#run-setup-list", OptionList).highlighted = None
        self.query_one("#run-setup-name", Input).value = ""
        self.query_one("#run-vram-ceiling", Input).value = ""
        self.query_one("#run-description", TextArea).text = ""
        self.remember()
        self.message("New run setup; enter a name to save it")

    def open_run_setup(self) -> None:
        ident = self.highlighted_run_setup()
        if ident is None:
            raise ValueError("Select a saved run setup")
        row = show_setup(ident)
        if row["suite_id"] != self.value("suite-id"):
            raise ValueError("Run setup belongs to another suite")
        self.run_setup_id = ident
        self.query_one("#run-setup-name", Input).value = row["name"]
        self.query_one("#run-vram-ceiling", Input).value = (
            f"{row['vram_ceiling_gib']:g}" if row["vram_ceiling_gib"] is not None else "")
        self.query_one("#run-description", TextArea).text = row["description"]
        self.pending_run_setup_delete = None
        self.remember()
        self.message(f"Opened run setup {row['name']}")

    def save_run_setup(self) -> str:
        ceiling = self.value("run-vram-ceiling")
        description = self.query_one("#run-description", TextArea).text
        name = self.value("run-setup-name") or (
            f"{ceiling} GiB run" if ceiling else
            next((line.strip()[:80] for line in description.splitlines() if line.strip()), "Run setup"))
        self.query_one("#run-setup-name", Input).value = name
        ident = save_setup(self.value("suite-id"), name, ceiling, description, self.run_setup_id)
        self.run_setup_id = ident
        self.refresh_run_setups(ident)
        self.remember()
        self.message(f"Saved run setup {self.value('run-setup-name')}")
        return ident

    def clone_run_setup(self) -> None:
        source = self.highlighted_run_setup() or self.run_setup_id
        if source is None:
            raise ValueError("Select a saved run setup to clone")
        ident = clone_setup(source)
        self.refresh_run_setups(ident)
        self.open_run_setup()
        self.query_one("#run-setup-name", Input).focus()
        self.message("Cloned setup; edit the copy and save your changes")

    def remove_run_setup(self) -> None:
        ident = self.highlighted_run_setup()
        if ident is None:
            raise ValueError("Select a saved run setup to delete")
        if self.pending_run_setup_delete != ident:
            self.pending_run_setup_delete = ident
            self.message("Press Delete again to remove this run setup; launched run snapshots remain")
            return
        delete_setup(ident)
        self.pending_run_setup_delete = None
        if self.run_setup_id == ident:
            self.new_run_setup()
        self.refresh_run_setups()
        self.message("Run setup deleted; launched run snapshots remain")

    def run_setup_for_launch(self) -> str | None:
        description = self.query_one("#run-description", TextArea).text
        if (self.run_setup_id or self.value("run-setup-name") or
                self.value("run-vram-ceiling") or description.strip()):
            return self.save_run_setup()
        return self.highlighted_run_setup()

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
            self.open_manual_editor("engine-list", editor_id, switch_mode=False)
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
            self.open_manual_editor("model-list", editor_id, switch_mode=False)
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
                       "engine-ref": item["ref_hint"], "engine-revision": item["revision"],
                       "engine-installed-path": item["installed_path"] or
                       (str(ROOT / "sources" / ident) if item["built_in"] and item["type"] == "git" else ""),
                       "engine-notes": item["notes"]})

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
            color = {"pending": "cyan", "needs_input": "yellow", "ready": "green", "confirmed": "green",
                     "canceled": "yellow", "failed": "red"}[request["status"]]
            status.update(f"[{color}]{request['status']}[/{color}]  ·  {escape(request['message'] or request['prompt'])}")
        else:
            status.update("Describe what you want. The agent will install it or ask a question.")
        ask = self.query_one(f"#{kind}-ask", Button)
        ask.label = ("Answer & retry" if request and request["status"] == "needs_input"
                     else "Retry agent" if request and request["status"] in {"canceled", "failed"}
                     else "Retry agent" if request and request["status"] == "pending" and request["id"] not in self.active_requests
                     else "Ask agent")
        ask.disabled = bool(request and (request["status"] == "ready" or request["id"] in self.active_requests))
        confirm = self.query_one(f"#{kind}-confirm", Button)
        confirm.display = bool(request and request["status"] == "ready")
        confirm.disabled = bool(request and request["id"] in self.active_requests)
        clear = self.query_one(f"#{kind}-clear", Button)
        clear.display = bool(request and request["status"] != "pending")

    def poll_requests(self) -> None:
        self.poll_tmux_sessions()
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
                resolve_request(request["id"], "failed", f"Completion rejected: {exc}")
            self.active_requests.discard(request["id"])
            (self.refresh_engines if kind == "engine" else self.refresh_models)()
            self.message(f"{kind.title()} request {request['id']}: {get_request(request['id'])['status']}")
        self.refresh_request("engine")
        self.refresh_request("model")
        if list_suites() != getattr(self, "suite_rows", []):
            self.refresh_suites()
        self.poll_suite_progress()

    def poll_tmux_sessions(self) -> None:
        for terminal_id, (tmux, socket) in list(self.tmux_sockets.items()):
            state, exit_code = self.tmux_pane_state(tmux, socket)
            if state == "dead":
                self.finish_embedded_terminal(terminal_id, exit_code or 0)
                continue
            if state == "running":
                self.tmux_missing.pop(terminal_id, None)
                continue
            self.tmux_missing[terminal_id] = self.tmux_missing.get(terminal_id, 0) + 1
            if self.tmux_missing[terminal_id] >= 2:
                self.finish_embedded_terminal(terminal_id, 1)

    def poll_suite_progress(self) -> None:
        suite_id = self.value("suite-id")
        banner = self.query_one("#suite-stage-status", Static)
        if not suite_id:
            banner.update("No suite selected")
            return
        try:
            status = show_suite(suite_id)["suite"]["status"]
        except ValueError:
            banner.update(f"{escape(suite_id)} · no suite plan yet")
            return
        if status != "frozen":
            banner.update(f"{escape(suite_id)} · draft plan · preparation in progress")
            return
        signal = preparation_signal(suite_id)
        if signal is None:
            banner.update(f"{escape(suite_id)} · plan frozen · agent completion not recorded")
            return
        session_open = any(info == ("suite", "prepare", suite_id) for info in self.terminals.values())
        tail = " · Codex terminal open" if session_open else ""
        banner.update(f"[green]{escape(suite_id)} · agent reported preparation complete · plan frozen{tail}[/green]")
        if suite_id not in self.announced_preparations:
            self.announced_preparations.add(suite_id)
            self.message(f"[green]Preparation complete: {escape(suite_id)}. Frozen plan is ready for review.[/green]")
            self.notify(f"{suite_id}: preparation complete", severity="information")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "suite-id":
            self.remember()
            self.poll_suite_progress()
            self.new_run_setup()
            self.refresh_run_setups()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = event.button.id
        try:
            if action == "engine-new":
                self.clear_manual_editor("engine")
            elif action == "model-new":
                self.clear_manual_editor("model")
            elif action in {"engine-edit", "model-edit"}:
                self.pending_delete = None
                kind = action.split("-")[0]
                selected = self.selected(f"#{kind}-list")
                if len(selected) != 1:
                    raise ValueError("Select exactly one item to edit")
                self.open_manual_editor(f"{kind}-list", selected[0])
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
            elif action in {"engine-clear", "model-clear"}:
                kind = action.split("-")[0]
                count = dismiss_requests(kind)
                self.refresh_request(kind)
                self.message(f"Cleared {count} completed {kind} setup notice(s)")
            elif action == "engine-build":
                self.launch_builds()
            elif action == "result-refresh":
                self.refresh_results()
            elif action == "result-pull":
                self.show_findings()
            elif action == "result-talk":
                key = self.highlighted_result()
                if not key:
                    raise ValueError("Select a run first")
                self.run_worker(self.start_results_agent(key, self.value("result-question")),
                                name=f"results-{key.replace('/', '-')}")
            elif action in {"prepare", "run"}:
                self.launch_agent(action)
            elif action == "suite-new":
                self.new_suite()
            elif action == "suite-open":
                self.open_suite()
            elif action == "suite-delete":
                self.remove_suite()
            elif action == "suite-create":
                self.save_suite_draft()
            elif action == "run-setup-new":
                self.new_run_setup()
            elif action == "run-setup-open":
                self.open_run_setup()
            elif action == "run-setup-clone":
                self.clone_run_setup()
            elif action == "run-setup-save":
                self.save_run_setup()
            elif action == "run-setup-delete":
                self.remove_run_setup()
            elif action and action.startswith("transcript-"):
                terminal = self.query_one(f"#{action.removeprefix('transcript-')}", CodexTerminal)
                terminal.toggle_transcript()
                terminal.focus()
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            self.message(f"[red]{exc}[/red]")
            self.notify(str(exc), severity="error")

    def save_engine(self) -> None:
        old = next((x for x in self.engines if x["id"] == self.edit_engine_id), None)
        if old and old["built_in"]:
            ident = update_builtin_engine(
                old["id"], self.value("engine-revision"), self.value("engine-installed-path"),
                self.value("engine-ref"),
            )
            self.refresh_engines(ident)
            self.message(f"Updated built-in engine {ident}")
            return
        kind = self.query_one("#engine-type", Select).value
        ident = save_engine({
            "id": self.edit_engine_id,
            "label": self.value("engine-label"), "type": kind,
            "locator": self.value("engine-locator"), "ref_hint": self.value("engine-ref"),
            "notes": self.value("engine-notes"), "revision": self.value("engine-revision"),
            "installed_path": self.value("engine-installed-path"),
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
        elif request and request["status"] in {"canceled", "failed"}:
            ident = create_request(kind, prompt_text or request["prompt"])
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

    def launch_builds(self) -> None:
        if shutil.which("codex") is None:
            raise ValueError("Codex CLI is not installed or not on PATH")
        selected = set(self.selected("#engine-list"))
        if not selected:
            raise ValueError("Select at least one Git engine to build")
        engines = [item for item in self.engines if item["id"] in selected and item["type"] == "git"]
        skipped = sorted(selected - {item["id"] for item in engines})
        pending = [item for item in engines if item["id"] not in self.active_builds]
        if not pending:
            raise ValueError("No selected Git engines to start; non-Git engines cannot be built and active builds are already running")
        if self.active_run_machine or any(info[0] == "suite" and info[1] == "run" for info in self.terminals.values()):
            raise ValueError("Close the active suite run before starting builds on this machine")
        self.query_one("#main-tabs", TabbedContent).active = "agents"
        for item in pending:
            self.active_builds.add(item["id"])
            self.run_worker(self.start_build_tab(item), name=f"build-{item['id']}")
        self.message(f"Started {len(pending)} build agent(s) in Agents: "
                     f"{', '.join(item['id'] for item in pending)}")
        if skipped:
            self.message(f"Skipped non-Git engines (no repository to build): {', '.join(skipped)}")

    async def start_build_tab(self, engine: dict) -> None:
        ident = engine["id"]
        key = uuid.uuid5(uuid.NAMESPACE_URL, ident).hex[:12]
        pane_id = f"build-agent-{key}"
        log_id = f"build-log-{key}"
        terminal_id = f"build-terminal-{uuid.uuid4().hex[:12]}"
        status_id = f"build-status-{key}"
        tabs = self.query_one("#agent-tabs", TabbedContent)
        try:
            if self.query(f"#{pane_id}"):
                await tabs.remove_pane(pane_id)
            prompt = make_build_prompt(engine)
            if self.embedded_terminal_available():
                command, socket = embedded_codex_command(prompt)
                terminal = CodexTerminal(command=command, id=terminal_id)
                terminal.tmux_mode = socket is not None
                toolbar = (Static("Mouse wheel: scroll history · q: return to Codex") if socket else
                           Button("Transcript / scroll history (Ctrl+T)", id=f"transcript-{terminal_id}"))
                self.terminals[terminal_id] = ("build", ident)
                if socket:
                    self.tmux_sockets[terminal_id] = (command[0], socket)
                await tabs.add_pane(TabPane(
                    f"build: {ident}", Static("Building…", id=status_id), toolbar, terminal, id=pane_id,
                ))
                tabs.active = pane_id
                self.query_one(f"#{terminal_id}").focus()
            else:
                await tabs.add_pane(TabPane(
                    f"build: {ident}", Static("Building…", id=status_id),
                    RichLog(id=log_id, highlight=True, markup=True, max_lines=500, wrap=True), id=pane_id,
                ))
                tabs.active = pane_id
                self.run_build_agent(ident, prompt, log_id)
        except Exception as exc:
            self.active_builds.discard(ident)
            self.cleanup_tmux(terminal_id)
            self.terminals.pop(terminal_id, None)
            self.message(f"[red]Could not start build agent for {escape(ident)}: {escape(str(exc))}[/red]")

    @work(thread=True)
    def run_build_agent(self, ident: str, prompt: str, log_id: str) -> None:
        try:
            process = subprocess.Popen(
                ["codex", "exec", "--json", "-C", str(ROOT), prompt],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                formatted = self.format_agent_event(line)
                if formatted:
                    self.call_from_thread(self.append_agent_log, log_id, formatted)
            self.call_from_thread(self.finish_build_agent, ident, process.wait())
        except OSError as exc:
            self.call_from_thread(self.append_agent_log, log_id, f"[red]{escape(str(exc))}[/red]")
            self.call_from_thread(self.finish_build_agent, ident, 1)

    def finish_build_agent(self, ident: str, exit_code: int) -> None:
        self.active_builds.discard(ident)
        status = (f"Agent exited ({exit_code}). Review its build and verification output; "
                  "Codex exit status alone does not prove a successful build.")
        key = uuid.uuid5(uuid.NAMESPACE_URL, ident).hex[:12]
        self.query_one(f"#build-status-{key}", Static).update(status)
        self.message(f"Build agent for {ident} exited ({exit_code}); review its Agents pane")

    async def start_agent_tab(self, kind: str, ident: str, prompt: str) -> None:
        pane_id = f"agent-{ident}"
        log_id = f"log-{ident}"
        tabs = self.query_one("#agent-tabs", TabbedContent)
        if self.embedded_terminal_available():
            terminal_id = f"terminal-{ident}"
            if self.query(f"#{pane_id}"):
                self.cleanup_tmux(terminal_id)
                self.terminals.pop(terminal_id, None)
                await tabs.remove_pane(pane_id)
            command, socket = embedded_codex_command(prompt)
            terminal = CodexTerminal(command=command, id=terminal_id)
            terminal.tmux_mode = socket is not None
            toolbar = (Static("Mouse wheel: scroll history · q: return to Codex") if socket else
                       Button("Transcript / scroll history (Ctrl+T)", id=f"transcript-{terminal_id}"))
            self.terminals[terminal_id] = ("setup", kind, ident)
            if socket:
                self.tmux_sockets[terminal_id] = (command[0], socket)
            await tabs.add_pane(TabPane(
                f"{kind}: {ident[-8:]}",
                toolbar,
                terminal,
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
                resolve_request(ident, "failed",
                                f"Agent stopped without a valid result ({detail}). Review its output and retry.")
        except (ValueError, OSError) as exc:
            resolve_request(ident, "failed",
                            f"Agent result was rejected: {exc}. Review its output and retry.")
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
        if stage == "run":
            if self.active_run_machine:
                raise ValueError("A suite run is already active on this machine")
            setup_id = self.run_setup_for_launch()
            self.active_run_machine = True
            self.run_worker(self.start_run_tab(suite_id, engines, models, setup_id),
                            name=f"run-{suite_id}")
            return
        check_updates = self.query_one("#check-updates", Checkbox).value if stage == "prepare" else False
        prompt = make_prompt(stage, suite_id, engines, models, check_updates)
        self.run_worker(self.start_suite_tab(stage, suite_id, engines, models, check_updates, prompt),
                        name=f"{stage}-{suite_id}")

    async def start_run_tab(self, suite_id: str, engines: list[str], models: list[str],
                            setup_id: str | None) -> None:
        terminal_id = f"run-terminal-{uuid.uuid4().hex[:12]}"
        try:
            await asyncio.to_thread(self.preflight_suite, "run", suite_id, engines, models, False)
            run = create_run(suite_id, setup_id)
            run_id = run["id"]
            prompt = make_prompt("run", suite_id, engines, models, False, run_id=run_id)
            pane_id = f"run-agent-{run_id}"
            log_id = f"run-log-{run_id}"
            tabs = self.query_one("#agent-tabs", TabbedContent)
            if self.embedded_terminal_available():
                command, socket = embedded_codex_command(prompt)
                terminal = CodexTerminal(command=command, id=terminal_id)
                terminal.tmux_mode = socket is not None
                toolbar = (Static("Mouse wheel: scroll history · q: return to Codex") if socket else
                           Button("Transcript / scroll history (Ctrl+T)", id=f"transcript-{terminal_id}"))
                self.terminals[terminal_id] = ("run", run_id)
                if socket:
                    self.tmux_sockets[terminal_id] = (command[0], socket)
                await tabs.add_pane(TabPane(f"run: {run['name']}", toolbar, terminal, id=pane_id))
                tabs.active = pane_id
                self.query_one("#main-tabs", TabbedContent).active = "agents"
                self.query_one(f"#{terminal_id}").focus()
            else:
                await tabs.add_pane(TabPane(
                    f"run: {run['name']}",
                    RichLog(id=log_id, highlight=True, markup=True, max_lines=500, wrap=True),
                    id=pane_id,
                ))
                tabs.active = pane_id
                self.query_one("#main-tabs", TabbedContent).active = "agents"
                self.append_agent_log(log_id, f"[cyan]Starting run {run_id}…[/cyan]")
                self.run_stored_agent(run_id, prompt, log_id)
            self.message(f"Run {run_id} started; instructions: uv run scripts/run_store.py show-run {run_id}")
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.active_run_machine = False
            self.cleanup_tmux(terminal_id)
            self.terminals.pop(terminal_id, None)
            self.message(f"[red]Run failed to start: {escape(str(exc))}[/red]")

    @work(thread=True)
    def run_stored_agent(self, run_id: str, prompt: str, log_id: str) -> None:
        try:
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
            self.call_from_thread(self.finish_stored_agent, run_id, process.wait())
        except OSError as exc:
            self.call_from_thread(self.append_agent_log, log_id, f"[red]{escape(str(exc))}[/red]")
            self.call_from_thread(self.finish_stored_agent, run_id, 1)

    def finish_stored_agent(self, run_id: str, exit_code: int) -> None:
        self.active_run_machine = False
        self.message(f"Run agent {run_id} exited ({exit_code}); review its results")

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
            self.refresh_suites()
            terminal_id = f"suite-terminal-{uuid.uuid4().hex[:12]}"
            if self.query(f"#{pane_id}"):
                for old_id, info in list(self.terminals.items()):
                    if info == ("suite", stage, suite_id):
                        self.cleanup_tmux(old_id)
                        self.terminals.pop(old_id, None)
                await tabs.remove_pane(pane_id)
            command, socket = embedded_codex_command(prompt)
            terminal = CodexTerminal(command=command, id=terminal_id)
            terminal.tmux_mode = socket is not None
            toolbar = (Static("Mouse wheel: scroll history · q: return to Codex") if socket else
                       Button("Transcript / scroll history (Ctrl+T)", id=f"transcript-{terminal_id}"))
            self.terminals[terminal_id] = ("suite", stage, suite_id)
            if socket:
                self.tmux_sockets[terminal_id] = (command[0], socket)
            await tabs.add_pane(TabPane(
                f"{stage}: {suite_id}",
                toolbar,
                terminal,
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
        self.finish_embedded_terminal(terminal_id, event.exit_code)

    def finish_embedded_terminal(self, terminal_id: str, exit_code: int) -> None:
        tmux_session = self.tmux_sockets.get(terminal_id)
        detached = False
        if tmux_session:
            state, pane_code = self.tmux_pane_state(*tmux_session)
            if state == "dead":
                exit_code = pane_code or 0
            elif state == "running":
                detached = True
        self.cleanup_tmux(terminal_id)
        info = self.terminals.pop(terminal_id, None)
        if not info:
            return
        if info[0] == "suite":
            _, stage, suite_id = info
            if stage == "prepare":
                status = show_suite(suite_id)["suite"]["status"]
                self.poll_suite_progress()
                self.message(f"Codex preparation session exited ({exit_code}); suite {suite_id}: {status}")
            else:
                self.message(f"Run agent exited with status {exit_code}; review its results")
            return
        if info[0] == "build":
            self.finish_build_agent(info[1], exit_code)
            return
        if info[0] == "run":
            self.finish_stored_agent(info[1], exit_code)
            return
        if info[0] == "results":
            self.finish_results_agent(info[1], exit_code)
            return
        _, kind, ident = info
        if get_request(ident)["status"] != "pending":
            self.active_requests.discard(ident)
            self.refresh_request(kind)
            return
        ids = request_results(ident)
        removals = request_removals(ident)
        signal = completion_signal(ident)
        try:
            if signal:
                resolve_request(ident, "ready", signal, ids)
            else:
                status = "canceled" if detached or exit_code in {0, 130, 143, -2, -15} else "failed"
                partial = " Saved catalog changes remain for review." if ids or removals else ""
                resolve_request(ident, status, f"Codex closed before completing setup (exit {exit_code}).{partial}")
        except (ValueError, OSError) as exc:
            resolve_request(ident, "failed", f"Agent result was rejected: {exc}. Review its output and retry.")
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
            self.poll_suite_progress()
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
