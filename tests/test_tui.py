"""Human setup and agent handoff tests; no network or real terminal needed."""

import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import ColorSystem
from textual.filter import Monochrome
from textual.widgets import Checkbox, Input, SelectionList, TabbedContent
from textual_tty import Terminal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import suite_store  # noqa: E402
import tui  # noqa: E402
import tui_data  # noqa: E402
from start_codex import make_prompt  # noqa: E402


class SetupTest(unittest.TestCase):
    def test_monochrome_terminal_uses_event_log(self) -> None:
        with patch.object(tui, "migrate_old_files", lambda: None):
            app = tui.BenchmarkApp()
        with patch.dict(os.environ, {"TERM": "xterm-256color", "NO_COLOR": "1"}):
            app.console._color_system = ColorSystem.EIGHT_BIT
            self.assertFalse(app.embedded_terminal_available())
        with patch.dict(os.environ, {"TERM": "dumb"}, clear=True):
            self.assertFalse(app.embedded_terminal_available())
        with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            self.assertTrue(app.embedded_terminal_available())

    def test_embedded_terminal_completes_validated_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            artifact = Path(temp) / "model.gguf"
            artifact.write_bytes(b"model")
            request = tui_data.create_request("model", "Find model", db)
            model = tui_data.save_model({"artifact": str(artifact), "label": "Local"}, db)
            tui_data.attach_request_result(request, model, db)
            with self.assertRaisesRegex(ValueError, "requested kind"):
                tui_data.attach_request_result(request, "upstream", db)

            real_terminal = Terminal
            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui, "latest_request", lambda kind: tui_data.latest_request(kind, db)),
                patch.object(tui, "get_request", lambda ident: tui_data.get_request(ident, db)),
                patch.object(tui, "request_results", lambda ident: tui_data.request_results(ident, db)),
                patch.object(tui, "resolve_request", lambda ident, status, message, result_ids=None:
                             tui_data.resolve_request(ident, status, message, result_ids, db)),
                patch.object(tui.BenchmarkApp, "embedded_terminal_available", lambda _self: True),
                patch.object(tui, "Terminal", lambda command, id: real_terminal(
                    command=["sh", "-c", "printf 'interactive\\n'"], id=id)),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    app._filters = [item for item in app._filters if not isinstance(item, Monochrome)]
                    async with app.run_test(size=(100, 35)) as pilot:
                        app.active_requests.add(request)
                        await app.start_agent_tab("model", request, "Test")
                        for _ in range(50):
                            await asyncio.sleep(0.01)
                            await pilot.pause()
                            if tui_data.get_request(request, db)["status"] == "ready":
                                break
                        self.assertEqual(tui_data.get_request(request, db)["status"], "ready")
                        self.assertFalse(app.active_requests)

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_embedded_suite_preflight_and_exit(self) -> None:
        created = []
        real_terminal = Terminal
        patches = [
            patch.object(tui, "migrate_old_files", lambda: None),
            patch.object(tui, "create_suite", lambda *args: created.append(args)),
            patch.object(tui, "show_suite", lambda _id: {"suite": {"status": "frozen"}}),
            patch.object(tui.BenchmarkApp, "embedded_terminal_available", lambda _self: True),
            patch.object(tui, "Terminal", lambda command, id: real_terminal(
                command=["sh", "-c", "printf 'suite\\n'"], id=id)),
        ]
        for item in patches:
            item.start()
        try:
            async def exercise():
                app = tui.BenchmarkApp()
                app._filters = [item for item in app._filters if not isinstance(item, Monochrome)]
                async with app.run_test(size=(100, 35)) as pilot:
                    await app.start_suite_tab("prepare", "demo-suite", ["upstream"], ["demo-model"], False, "Test")
                    for _ in range(50):
                        await asyncio.sleep(0.01)
                        await pilot.pause()
                        if not app.terminals:
                            break
                    self.assertEqual(created[0][0], "demo-suite")
                    self.assertFalse(app.terminals)

            asyncio.run(exercise())
        finally:
            for item in reversed(patches):
                item.stop()

    def test_tui_generates_ids_and_persists_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "save_engine", lambda item: tui_data.save_engine(item, db)),
                patch.object(tui, "save_model", lambda item: tui_data.save_model(item, db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui, "latest_request", lambda kind: tui_data.latest_request(kind, db)),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 35)) as pilot:
                        self.assertFalse(app.query_one("#model-list").display)
                        self.assertTrue(app.query_one("#model-empty").display)
                        app.query_one("#engine-label", Input).value = "My engine"
                        app.query_one("#engine-locator", Input).value = "https://example.org/engine.git"
                        app.save_engine()
                        engine_id = next(x["id"] for x in tui_data.list_engines(db) if not x["built_in"])
                        self.assertTrue(engine_id.startswith("my-engine-"))

                        app.query_one("#model-label", Input).value = "My model"
                        app.query_one("#model-artifact", Input).value = "/tmp/my-model.gguf"
                        app.save_model()
                        model_id = tui_data.list_models(db)[0]["id"]
                        self.assertTrue(model_id.startswith("my-model-"))

                        app.query_one("#engine-list", SelectionList).select(engine_id)
                        app.query_one("#model-list", SelectionList).select(model_id)
                        app.query_one("#suite-id", Input).value = "sample-suite"
                        app.query_one("#check-updates", Checkbox).value = True
                        app.remember()
                        self.assertFalse(app.query_one("#model-manual").display)
                        self.assertTrue(app.query_one("#model-agent").display)
                        app.query(TabbedContent).first().active = "models"
                        await pilot.pause()
                        self.assertGreater(app.query_one("#model-mode").region.y,
                                           app.query_one("#model-agent").region.y)
                        app.mode["model"] = "manual"
                        app.update_modes()
                        self.assertTrue(app.query_one("#model-manual").display)
                        self.assertFalse(app.query_one("#model-agent").display)
                        state = tui_data.load_state(db)
                        self.assertIn(engine_id, state["engines"])
                        self.assertEqual(state["models"], [model_id])
                        self.assertTrue(state["check_updates"])
                        await pilot.pause()

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_agent_request_questions_and_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            artifact = Path(temp) / "model.gguf"
            artifact.write_bytes(b"model")
            ident = tui_data.create_request("model", "Install a good local model", db)
            with self.assertRaisesRegex(ValueError, "result ID"):
                tui_data.resolve_request(ident, "ready", "Done", path=db)
            tui_data.resolve_request(ident, "needs_input", "Which quantization?", path=db)
            self.assertEqual(tui_data.get_request(ident, db)["status"], "needs_input")
            tui_data.answer_request(ident, "Q4_K_M", db)
            model = tui_data.save_model({"artifact": str(artifact), "label": "Q4"}, db)
            tui_data.resolve_request(ident, "ready", "Installed and checked local artifact",
                                     [model], db)
            self.assertEqual(tui_data.confirm_request(ident, db), [model])
            self.assertEqual(tui_data.get_request(ident, db)["status"], "confirmed")
            with self.assertRaisesRegex(ValueError, "Confirmed"):
                tui_data.resolve_request(ident, "needs_input", "More questions", path=db)
            missing = tui_data.save_model({"artifact": str(Path(temp) / "missing.gguf")}, db)
            another = tui_data.create_request("model", "Install another model", db)
            with self.assertRaisesRegex(ValueError, "does not exist"):
                tui_data.resolve_request(another, "ready", "Done", [missing], db)

    def test_git_request_requires_verified_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "catalog.sqlite3"
            checkout = root / "engine"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            (checkout / "README").write_text("engine")
            subprocess.run(["git", "-C", str(checkout), "add", "README"], check=True)
            subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Test",
                            "-c", "user.email=test@example.com", "commit", "-qm", "initial"], check=True)
            head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            request = tui_data.create_request("engine", "Install a fork", db)
            ident = tui_data.save_engine({
                "label": "Fork", "type": "git", "locator": "https://example.org/fork.git",
                "revision": "0" * 40, "installed_path": str(checkout),
            }, db)
            with self.assertRaisesRegex(ValueError, "does not match"):
                tui_data.resolve_request(request, "ready", "Installed", [ident], db)
            tui_data.save_engine({
                "id": ident, "label": "Fork", "type": "git",
                "locator": "https://example.org/fork.git", "revision": head,
                "installed_path": str(checkout),
            }, db)
            tui_data.resolve_request(request, "ready", "Verified checkout", [ident], db)
            self.assertEqual(tui_data.confirm_request(request, db), [ident])

    def test_ask_agent_runs_background_exec_and_polls_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            artifact = Path(temp) / "model.gguf"
            artifact.write_bytes(b"model")
            model = tui_data.save_model({"artifact": str(artifact), "label": "Local"}, db)
            commands = []

            class FakeProcess:
                stdout = io.StringIO('{"type":"thread.started"}\n{"type":"turn.completed"}\n')

                def __init__(self, command, **_kwargs):
                    commands.append(command)
                    response = Path(command[command.index("--output-last-message") + 1])
                    response.write_text(json.dumps({
                        "status": "ready", "message": "Verified local model",
                        "result_ids": [model],
                    }))

                def wait(self):
                    return 0

            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui, "create_request", lambda kind, prompt: tui_data.create_request(kind, prompt, db)),
                patch.object(tui, "latest_request", lambda kind: tui_data.latest_request(kind, db)),
                patch.object(tui, "get_request", lambda ident: tui_data.get_request(ident, db)),
                patch.object(tui, "resolve_request", lambda ident, status, message, result_ids=None:
                             tui_data.resolve_request(ident, status, message, result_ids, db)),
                patch.object(tui.shutil, "which", lambda _name: "/usr/bin/codex"),
                patch.object(tui.subprocess, "Popen", FakeProcess),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 35)) as pilot:
                        app.query_one("#model-request", Input).value = "Find my local model"
                        app.handle_request("model", "ask")
                        for _ in range(30):
                            await asyncio.sleep(0.01)
                            await pilot.pause()
                            if tui_data.latest_request("model", db)["status"] == "ready":
                                break
                        self.assertEqual(tui_data.latest_request("model", db)["status"], "ready")
                        self.assertEqual(commands[0][:3], ["codex", "exec", "--json"])
                        self.assertTrue(app.query_one("#model-confirm").display)
                        self.assertIsNotNone(app.query_one("#agent-tabs").active)

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_suite_prepare_runs_in_agents_tab(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            engine = tui_data.save_engine({"label": "Demo", "type": "git",
                                           "locator": "https://example.org/demo.git"}, db)
            model = tui_data.save_model({"artifact": "/tmp/demo.gguf", "label": "Demo"}, db)
            commands = []
            created = []

            class FakeProcess:
                stdout = io.StringIO('{"type":"turn.completed"}\n')

                def __init__(self, command, **_kwargs):
                    commands.append(command)

                def wait(self):
                    return 0

            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui, "latest_request", lambda kind: tui_data.latest_request(kind, db)),
                patch.object(tui, "create_suite", lambda *args: created.append(args)),
                patch.object(tui, "show_suite", lambda _id: {"suite": {"status": "frozen"}}),
                patch.object(tui.shutil, "which", lambda _name: "/usr/bin/codex"),
                patch.object(tui.subprocess, "Popen", FakeProcess),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 35)) as pilot:
                        app.query_one("#engine-list", SelectionList).select(engine)
                        app.query_one("#model-list", SelectionList).select(model)
                        app.query_one("#suite-id", Input).value = "demo-suite"
                        app.launch_agent("prepare")
                        for _ in range(30):
                            await asyncio.sleep(0.01)
                            await pilot.pause()
                            if commands:
                                break
                        self.assertEqual(commands[0][:3], ["codex", "exec", "--json"])
                        self.assertEqual(created[0][0], "demo-suite")
                        self.assertIsNotNone(app.query_one("#agent-tabs").active)

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_code_rejects_incomplete_plan_and_hashes_local_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "catalog.sqlite3"
            artifact = root / "tiny.gguf"
            artifact.write_bytes(b"test artifact")
            checkout = root / "engine"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            (checkout / "README").write_text("engine")
            subprocess.run(["git", "-C", str(checkout), "add", "README"], check=True)
            subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Test",
                            "-c", "user.email=test@example.com", "commit", "-qm", "initial"], check=True)
            head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            engine = tui_data.save_engine({
                "label": "Demo", "type": "git",
                "locator": "https://example.org/demo.git",
                "installed_path": str(checkout), "revision": head,
            }, db)
            model = tui_data.save_model({"label": "Tiny", "artifact": str(artifact)}, db)
            suite_store.create_suite("demo-suite", [engine], [model], False, db)
            with self.assertRaisesRegex(ValueError, "incomplete"):
                suite_store.freeze_suite("demo-suite", db)
            with self.assertRaisesRegex(ValueError, "40-character"):
                suite_store.record_engine("demo-suite", engine, "main", db)
            suite_store.record_engine("demo-suite", engine, head, db)
            digest = suite_store.record_model("demo-suite", model, tokenizer="example/tokenizer", path=db)
            self.assertEqual(len(digest), 64)
            for method in suite_store.METHODS:
                suite_store.record_packet("demo-suite", {
                    "engine_id": engine, "model_id": model, "method": method,
                    "support": "supported", "command": ["server", "--model", str(artifact)],
                    "tuning_rationale": "Baseline", "memory_target": "8 GiB",
                }, db)
            suite_store.freeze_suite("demo-suite", db)
            self.assertEqual(suite_store.show_suite("demo-suite", db)["suite"]["status"], "frozen")
            with self.assertRaisesRegex(ValueError, "frozen"):
                suite_store.record_engine("demo-suite", engine, head, db)
            artifact.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                suite_store.validate_suite("demo-suite", db)

    def test_agent_prompt_uses_validated_storage(self) -> None:
        prompt = make_prompt("prepare", "demo-suite", ["engine"], ["model"], False)
        self.assertIn("suite_store.py freeze demo-suite", prompt)
        self.assertIn("do not claim the plan is frozen", prompt)

    def test_agent_events_are_readable(self) -> None:
        started = tui.BenchmarkApp.format_agent_event(json.dumps({
            "type": "item.started", "item": {
                "type": "command_execution", "command": "/usr/bin/zsh -lc 'ls -lah /tmp/models'",
            },
        }))
        self.assertIn("Running", started)
        self.assertIn("ls -lah /tmp/models", started)
        self.assertNotIn("/usr/bin/zsh", started)
        completed = tui.BenchmarkApp.format_agent_event(json.dumps({
            "type": "item.completed", "item": {
                "type": "command_execution", "command": "ls -lah /tmp/models",
                "exit_code": 0, "aggregated_output": "",
            },
        }))
        self.assertIsNone(completed)
        failed = tui.BenchmarkApp.format_agent_event(json.dumps({
            "type": "item.completed", "item": {
                "type": "command_execution", "exit_code": 2, "aggregated_output": "not found",
            },
        }))
        self.assertIn("Command failed (2)", failed)
        message = tui.BenchmarkApp.format_agent_event(json.dumps({
            "type": "item.completed", "item": {
                "type": "agent_message", "text": "I found the requested model.",
            },
        }))
        self.assertIn("I found the requested model.", message)


if __name__ == "__main__":
    unittest.main()
