"""Human setup and agent handoff tests; no network or real terminal needed."""

import asyncio
import contextlib
import io
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rich.console import ColorSystem
from textual.app import App, ComposeResult
from textual.filter import Monochrome
from textual.widgets import Checkbox, Input, OptionList, SelectionList, TabbedContent, TextArea
from textual_tty import Terminal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import suite_store  # noqa: E402
import run_store  # noqa: E402
import catalog_cli  # noqa: E402
import tui  # noqa: E402
import tui_data  # noqa: E402
from start_codex import make_prompt  # noqa: E402


class SetupTest(unittest.TestCase):
    def test_run_setup_edit_clone_and_launch_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            with suite_store.database(db) as connection:
                connection.execute("INSERT INTO suites VALUES (?,?,?)", ("demo", "draft", 0))
            original = run_store.save_setup("demo", "8 GiB", 8, "Favor GPU cache", path=db)
            copy = run_store.clone_setup(original, path=db)
            self.assertNotEqual(copy, original)
            self.assertEqual(run_store.show_setup(copy, db)["vram_ceiling_gib"], 8)
            run_store.save_setup("demo", "12 GiB", 12, "Tune the cache", copy, path=db)
            self.assertEqual(run_store.show_setup(original, db)["description"], "Favor GPU cache")
            with self.assertRaisesRegex(ValueError, "Freeze"):
                run_store.create_run("demo", copy, db)
            with suite_store.database(db) as connection:
                connection.execute("UPDATE suites SET status='frozen' WHERE id='demo'")
                connection.execute("INSERT INTO suite_engines(suite_id,engine_id,setup_json) VALUES (?,?,?)",
                                   ("demo", "engine", "{}"))
            launched = run_store.create_run("demo", copy, db)
            run_store.save_setup("demo", "14 GiB", 14, "Changed later", copy, path=db)
            self.assertEqual(run_store.show_run(launched["id"], db)["description"], "Tune the cache")
            self.assertEqual(run_store.show_run(launched["id"], db)["vram_ceiling_gib"], 12)
            self.assertIn(launched["id"], launched["output_dir"])
            self.assertEqual(run_store.record_peak(launched["id"], "engine", "baseline", 12000, db)["status"],
                             "within_ceiling")
            self.assertEqual(run_store.record_peak(launched["id"], "engine", "cache", 13000, db)["status"],
                             "exceeded")
            self.assertEqual(len(run_store.list_peaks(launched["id"], db)), 2)
            with self.assertRaisesRegex(ValueError, "already recorded"):
                run_store.record_peak(launched["id"], "engine", "cache", 11000, db)
            run_store.delete_setup(copy, db)
            self.assertEqual(run_store.show_run(launched["id"], db)["name"], "12 GiB")
            for invalid in (0, -1, "nan", "inf", "nope"):
                with self.assertRaises(ValueError):
                    run_store.save_setup("demo", "bad", invalid, path=db)

    def test_tui_can_clone_and_edit_run_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            with suite_store.database(db) as connection:
                connection.execute("INSERT INTO suites VALUES (?,?,?)", ("demo", "frozen", 0))
            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui, "list_setups", lambda suite: run_store.list_setups(suite, db)),
                patch.object(tui, "show_setup", lambda ident: run_store.show_setup(ident, db)),
                patch.object(tui, "save_setup", lambda suite, name, ceiling, desc, ident:
                             run_store.save_setup(suite, name, ceiling, desc, ident, db)),
                patch.object(tui, "clone_setup", lambda ident: run_store.clone_setup(ident, path=db)),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 40)):
                        app.query_one("#suite-id", Input).value = "demo"
                        app.query_one("#run-setup-name", Input).value = "8 GiB"
                        app.query_one("#run-vram-ceiling", Input).value = "8"
                        app.query_one("#run-description", TextArea).text = "Start with a small cache"
                        original = app.save_run_setup()
                        app.clone_run_setup()
                        self.assertNotEqual(app.run_setup_id, original)
                        app.query_one("#run-vram-ceiling", Input).value = "12"
                        app.query_one("#run-description", TextArea).text = "Use the spare VRAM"
                        copy = app.save_run_setup()
                        self.assertEqual(run_store.show_setup(copy, db)["vram_ceiling_gib"], 12)
                        self.assertEqual(run_store.show_setup(original, db)["vram_ceiling_gib"], 8)

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_run_agent_receives_immutable_run_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            engine = tui_data.save_engine({"label": "Demo", "type": "git",
                                           "locator": "https://example.org/demo.git"}, db)
            model = tui_data.save_model({"artifact": "/tmp/demo.gguf", "label": "Demo"}, db)
            with suite_store.database(db) as connection:
                connection.execute("INSERT INTO suites VALUES (?,?,?)", ("demo", "frozen", 0))
            captured = []
            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui, "list_setups", lambda suite: run_store.list_setups(suite, db)),
                patch.object(tui, "save_setup", lambda suite, name, ceiling, desc, ident:
                             run_store.save_setup(suite, name, ceiling, desc, ident, db)),
                patch.object(tui, "create_run", lambda suite, setup: run_store.create_run(suite, setup, db)),
                patch.object(tui.BenchmarkApp, "preflight_suite", staticmethod(lambda *_args: None)),
                patch.object(tui.BenchmarkApp, "embedded_terminal_available", lambda _self: False),
                patch.object(tui.BenchmarkApp, "run_stored_agent", lambda _self, ident, prompt, log:
                             captured.append((ident, prompt, log))),
                patch.object(tui.shutil, "which", lambda _name: "/usr/bin/codex"),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 40)) as pilot:
                        app.query_one("#engine-list", SelectionList).select(engine)
                        app.query_one("#model-list", SelectionList).select(model)
                        app.query_one("#suite-id", Input).value = "demo"
                        app.query_one("#run-setup-name", Input).value = "12 GiB"
                        app.query_one("#run-vram-ceiling", Input).value = "12"
                        app.query_one("#run-description", TextArea).text = "Tune cache capacity"
                        app.launch_agent("run")
                        for _ in range(40):
                            await asyncio.sleep(0.01)
                            await pilot.pause()
                            if captured:
                                break
                        self.assertTrue(captured)
                        run_id, prompt, _ = captured[0]
                        self.assertIn(f"show-run {run_id}", prompt)
                        self.assertEqual(run_store.show_run(run_id, db)["description"], "Tune cache capacity")
                        self.assertEqual(run_store.show_run(run_id, db)["vram_ceiling_gib"], 12)

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_build_selected_starts_one_pane_per_git_engine(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            first = tui_data.save_engine({"label": "First", "type": "git", "locator": "https://example.org/one.git"}, db)
            second = tui_data.save_engine({"label": "Second", "type": "git", "locator": "https://example.org/two.git"}, db)
            remote = tui_data.save_engine({"label": "Remote", "type": "remote", "locator": "service"}, db)
            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui.BenchmarkApp, "embedded_terminal_available", lambda _self: True),
                patch.object(tui.shutil, "which", lambda program: "/usr/bin/codex" if program == "codex" else None),
                patch.object(tui, "embedded_codex_command", lambda prompt: (["codex"], None)),
                patch.object(tui, "CodexTerminal", lambda command, id: Terminal(
                    command=["sh", "-c", "sleep 0.2"], id=id)),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    app._filters = [item for item in app._filters if not isinstance(item, Monochrome)]
                    async with app.run_test(size=(100, 35)) as pilot:
                        picker = app.query_one("#engine-list", SelectionList)
                        for ident in (first, second, remote):
                            picker.select(ident)
                        app.launch_builds()
                        for _ in range(30):
                            await asyncio.sleep(0.01)
                            await pilot.pause()
                            if len(app.query("#agent-tabs TabPane")) >= 3:
                                break
                        self.assertEqual(app.query_one("#main-tabs", TabbedContent).active, "agents")
                        self.assertEqual(len(app.query("#agent-tabs TabPane")), 3)
                        self.assertIn("Build the selected Git engine", tui.make_build_prompt(app.engines[0]))
                        for _ in range(60):
                            await asyncio.sleep(0.01)
                            await pilot.pause()
                            if not app.active_builds:
                                break
                        self.assertFalse(app.active_builds)
                        self.assertEqual(len([node for node in app.query("#agent-tabs Static")
                                              if node.id and node.id.startswith("build-status-")]), 2)

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_existing_update_and_removal_catalog_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            artifact = Path(temp) / "model.gguf"
            artifact.write_bytes(b"model")
            ident = tui_data.save_model({"artifact": str(artifact), "label": "Old"}, db)
            request = tui_data.create_request("model", "Use the installed model", db)
            patches = [
                patch.object(catalog_cli, "get_request", lambda item: tui_data.get_request(item, db)),
                patch.object(catalog_cli, "list_models", lambda: tui_data.list_models(db)),
                patch.object(catalog_cli, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(catalog_cli, "attach_request_result", lambda req, item:
                             tui_data.attach_request_result(req, item, db)),
                patch.object(catalog_cli, "save_model", lambda item: tui_data.save_model(item, db)),
                patch.object(catalog_cli, "remove_for_request", lambda kind, item, req, **kwargs:
                             tui_data.remove_for_request(kind, item, req, path=db, **kwargs)),
            ]
            for item in patches:
                item.start()
            try:
                def cli(*args):
                    with patch.object(sys, "argv", ["catalog_cli.py", *args]), contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(catalog_cli.main(), 0)

                cli("use-existing", request, ident)
                self.assertEqual(tui_data.request_results(request, db), [ident])
                with patch.object(catalog_cli, "signal_request_complete", lambda req, message:
                                  tui_data.signal_request_complete(req, message, db)):
                    cli("finish-request", request, "--message", "Verified existing model")
                self.assertEqual(tui_data.completion_signal(request, db), "Verified existing model")
                tui_data.resolve_request(request, "ready", "Verified existing model", [ident], db)
                self.assertEqual(tui_data.confirm_request(request, db), [ident])

                update = tui_data.create_request("model", "Update the model name", db)
                cli("update-model", ident, "--request-id", update, "--name", "New")
                self.assertEqual(tui_data.list_models(db)[0]["label"], "New")
                self.assertEqual(tui_data.list_models(db)[0]["artifact"], str(artifact))
                self.assertEqual(tui_data.request_results(update, db), [ident])

                removal = tui_data.create_request("model", "Remove the catalog entry", db)
                cli("remove-model", ident, "--request-id", removal)
                self.assertTrue(artifact.exists())
                self.assertEqual(tui_data.list_models(db), [])
                tui_data.resolve_request(removal, "ready", "Removed catalog entry", [], db)
                self.assertEqual(tui_data.confirm_request(removal, db), [])
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_poll_completes_request_without_agent_process_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            artifact = Path(temp) / "model.gguf"
            artifact.write_bytes(b"model")
            ident = tui_data.save_model({"artifact": str(artifact)}, db)
            request = tui_data.create_request("model", "Use installed model", db)
            tui_data.attach_request_result(request, ident, db)
            tui_data.signal_request_complete(request, "Verified installed model", db)
            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui, "latest_request", lambda kind: tui_data.latest_request(kind, db)),
                patch.object(tui, "completion_signal", lambda req: tui_data.completion_signal(req, db)),
                patch.object(tui, "request_results", lambda req: tui_data.request_results(req, db)),
                patch.object(tui, "get_request", lambda req: tui_data.get_request(req, db)),
                patch.object(tui, "resolve_request", lambda req, status, message, ids=None:
                             tui_data.resolve_request(req, status, message, ids, db)),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 35)):
                        app.active_requests.add(request)
                        app.poll_requests()
                        self.assertEqual(tui_data.get_request(request, db)["status"], "ready")
                        self.assertFalse(app.active_requests)

                asyncio.run(exercise())
                closing = tui_data.create_request("model", "Find another model", db)

                async def close_app():
                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 35)):
                        app.terminals["closing"] = ("setup", "model", closing)

                asyncio.run(close_app())
                self.assertEqual(tui_data.get_request(closing, db)["status"], "canceled")
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_suite_banner_announces_preparation_without_codex_exit(self) -> None:
        patches = [
            patch.object(tui, "migrate_old_files", lambda: None),
            patch.object(tui, "show_suite", lambda _id: {"suite": {"status": "frozen"}}),
            patch.object(tui, "preparation_signal", lambda _id: {"message": "Reviewed plan"}),
        ]
        for item in patches:
            item.start()
        try:
            async def exercise():
                app = tui.BenchmarkApp()
                async with app.run_test(size=(100, 35)):
                    app.query_one("#suite-id", Input).value = "demo-suite"
                    app.terminals["still-open"] = ("suite", "prepare", "demo-suite")
                    app.poll_suite_progress()
                    banner = str(app.query_one("#suite-stage-status").content)
                    self.assertIn("agent reported preparation complete", banner)
                    self.assertIn("Codex terminal open", banner)
                    self.assertIn("demo-suite", app.announced_preparations)

            asyncio.run(exercise())
        finally:
            for item in reversed(patches):
                item.stop()

    def test_file_removal_requires_exact_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            artifact = Path(temp) / "model.gguf"
            artifact.write_bytes(b"model")
            ident = tui_data.save_model({"artifact": str(artifact), "label": "Local"}, db)
            request = tui_data.create_request("model", "Uninstall local model", db)
            with self.assertRaisesRegex(ValueError, "confirm-path"):
                tui_data.remove_for_request("model", ident, request, True, str(Path(temp) / "wrong"), db)
            self.assertTrue(artifact.exists())
            tui_data.remove_for_request("model", ident, request, True, str(artifact), db)
            self.assertFalse(artifact.exists())
            tui_data.resolve_request(request, "ready", "Uninstalled local model", [], db)
            self.assertEqual(tui_data.request_removals(request, db)[0]["deleted_install"], 1)

    def test_builtin_engine_local_update_and_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "catalog.sqlite3"
            checkout = root / "sources" / "upstream"
            checkout.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            (checkout / "README").write_text("engine")
            subprocess.run(["git", "-C", str(checkout), "add", "README"], check=True)
            subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Test",
                            "-c", "user.email=test@example.com", "commit", "-qm", "initial"], check=True)
            head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            with patch.object(tui_data, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "match"):
                    tui_data.update_builtin_engine("upstream", "0" * 40, str(checkout), "master", db)
                tui_data.update_builtin_engine("upstream", head, str(checkout), "master", db)
                self.assertEqual(next(x for x in tui_data.list_engines(db) if x["id"] == "upstream")["revision"], head)
                request = tui_data.create_request("engine", "Uninstall upstream checkout", db)
                tui_data.remove_for_request("engine", "upstream", request, True, str(checkout), db)
                self.assertFalse(checkout.exists())
                self.assertTrue(any(x["id"] == "upstream" for x in tui_data.list_engines(db)))
                tui_data.resolve_request(request, "ready", "Removed local checkout", [], db)
                self.assertEqual(tui_data.request_removals(request, db)[0]["catalog_removed"], 0)

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
            tui_data.signal_request_complete(request, "Verified local model", db)
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
                patch.object(tui, "completion_signal", lambda ident: tui_data.completion_signal(ident, db)),
                patch.object(tui, "resolve_request", lambda ident, status, message, result_ids=None:
                             tui_data.resolve_request(ident, status, message, result_ids, db)),
                patch.object(tui.BenchmarkApp, "embedded_terminal_available", lambda _self: True),
                patch.object(tui, "embedded_codex_command", lambda prompt: (["codex"], None)),
                patch.object(tui, "CodexTerminal", lambda command, id: real_terminal(
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

    def test_closed_setup_terminal_is_canceled_and_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            request = tui_data.create_request("model", "Find local model", db)
            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui, "latest_request", lambda kind: tui_data.latest_request(kind, db)),
                patch.object(tui, "get_request", lambda ident: tui_data.get_request(ident, db)),
                patch.object(tui, "request_results", lambda ident: tui_data.request_results(ident, db)),
                patch.object(tui, "request_removals", lambda ident: tui_data.request_removals(ident, db)),
                patch.object(tui, "completion_signal", lambda ident: tui_data.completion_signal(ident, db)),
                patch.object(tui, "resolve_request", lambda ident, status, message, result_ids=None:
                             tui_data.resolve_request(ident, status, message, result_ids, db)),
                patch.object(tui, "create_request", lambda kind, prompt: tui_data.create_request(kind, prompt, db)),
                patch.object(tui.BenchmarkApp, "embedded_terminal_available", lambda _self: True),
                patch.object(tui, "embedded_codex_command", lambda prompt: (["codex"], None)),
                patch.object(tui, "CodexTerminal", lambda command, id: Terminal(
                    command=["sh", "-c", "exit 0"], id=id)),
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
                            if tui_data.get_request(request, db)["status"] == "canceled":
                                break
                        self.assertEqual(tui_data.get_request(request, db)["status"], "canceled")
                        self.assertEqual(str(app.query_one("#model-ask").label), "Retry agent")
                        self.assertFalse(app.active_requests)
                        app.query_one("#model-request", Input).value = ""
                        with patch.object(app, "run_worker", side_effect=lambda coroutine, **_kwargs: coroutine.close()):
                            app.handle_request("model", "ask")
                        retried = tui_data.latest_request("model", db)
                        self.assertNotEqual(retried["id"], request)
                        self.assertEqual(retried["prompt"], "Find local model")
                        app.terminals["failed-agent"] = ("setup", "model", retried["id"])
                        app.finish_embedded_terminal("failed-agent", 9)
                        self.assertEqual(tui_data.get_request(retried["id"], db)["status"], "failed")
                        vanished = tui_data.create_request("model", "Find third model", db)
                        app.terminals["vanished"] = ("setup", "model", vanished)
                        app.tmux_sockets["vanished"] = ("/usr/bin/tmux", "llmbench-test-vanished")
                        with patch.object(tui.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
                            app.poll_tmux_sessions()
                            self.assertEqual(tui_data.get_request(vanished, db)["status"], "pending")
                            app.poll_tmux_sessions()
                        self.assertEqual(tui_data.get_request(vanished, db)["status"], "failed")
                        self.assertNotIn("vanished", app.tmux_sockets)

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_old_request_schema_migrates_for_canceled_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            with sqlite3.connect(db) as connection:
                connection.execute("""CREATE TABLE requests (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('engine','model')),
                    prompt TEXT NOT NULL, status TEXT NOT NULL
                        CHECK(status IN ('pending','needs_input','ready','confirmed')),
                    message TEXT NOT NULL DEFAULT '', result_ids TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
                connection.execute("INSERT INTO requests(id,kind,prompt,status) VALUES ('old','model','Find it','pending')")
            connection.close()
            tui_data.resolve_request("old", "canceled", "Closed by user", path=db)
            self.assertEqual(tui_data.get_request("old", db)["status"], "canceled")

    def test_clear_status_hides_completed_model_requests(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            earlier = tui_data.create_request("model", "Find A", db)
            tui_data.resolve_request(earlier, "needs_input", "Which quant?", path=db)
            recent = tui_data.create_request("model", "Find B", db)
            tui_data.resolve_request(recent, "failed", "Agent exited", path=db)
            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui, "latest_request", lambda kind: tui_data.latest_request(kind, db)),
                patch.object(tui, "dismiss_requests", lambda kind: tui_data.dismiss_requests(kind, db)),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 40)) as pilot:
                        app.query(TabbedContent).first().active = "models"
                        await pilot.pause()
                        self.assertTrue(app.query_one("#model-clear").display)
                        await pilot.click("#model-clear")
                        self.assertIsNone(tui_data.latest_request("model", db))
                        self.assertIn("Describe what you want", str(app.query_one("#model-agent-status").content))

                asyncio.run(exercise())
                self.assertEqual(tui_data.get_request(recent, db)["status"], "failed")
                self.assertEqual(tui_data.get_request(earlier, db)["status"], "needs_input")
            finally:
                for item in reversed(patches):
                    item.stop()

    @unittest.skipUnless(shutil.which("tmux") and hasattr(os, "getuid"), "tmux is optional")
    def test_tmux_wheel_scrolls_history_and_teardown_is_isolated(self) -> None:
        tmux = shutil.which("tmux")
        socket = f"llmbench-test-{uuid.uuid4().hex[:10]}"
        other = f"llmbench-other-{uuid.uuid4().hex[:10]}"
        command = [tmux, "-L", socket, "-f", str(tui.TMUX_CONFIG), "new-session", "-s", "agent",
                   "--", "sh -c 'seq 1 100; sleep 10'"]

        class Probe(App):
            def compose(self) -> ComposeResult:
                yield tui.CodexTerminal(command=command, id="terminal")

        try:
            subprocess.run([tmux, "-L", other, "-f", "/dev/null", "new-session", "-d", "-s", "other",
                            "--", "sleep 10"], check=True)

            async def exercise():
                app = Probe()
                app._filters = [item for item in app._filters if not isinstance(item, Monochrome)]
                async with app.run_test(size=(90, 30)) as pilot:
                    terminal = app.query_one("#terminal", tui.CodexTerminal)
                    terminal.tmux_mode = True
                    for _ in range(20):
                        await asyncio.sleep(0.02)
                        await pilot.pause()
                        top = terminal.board.blitter.current_buffer.get_line_text(0).strip()
                        if top.isdigit() and int(top) >= 70:
                            break
                    self.assertTrue(top.isdigit(), top)
                    terminal.on_mouse_scroll_up(SimpleNamespace(
                        offset=SimpleNamespace(x=5, y=5), stop=lambda: None))
                    for _ in range(20):
                        await asyncio.sleep(0.02)
                        await pilot.pause()
                        scrolled = terminal.board.blitter.current_buffer.get_line_text(0).strip().split()[0]
                        if scrolled.isdigit() and int(scrolled) < int(top):
                            break
                    self.assertLess(int(scrolled), int(top))
                    self.assertEqual(subprocess.check_output(
                        [tmux, "-L", socket, "display-message", "-p", "-t", "agent", "#{pane_in_mode}"],
                        text=True).strip(), "1")
                    return terminal.board.process

            client = asyncio.run(exercise())
            if client is not None:
                client.wait(timeout=2)

            async def teardown():
                app = tui.BenchmarkApp()
                async with app.run_test(size=(90, 30)):
                    app.tmux_sockets["terminal"] = (tmux, socket)

            with patch.object(tui, "migrate_old_files", lambda: None):
                asyncio.run(teardown())
            self.assertNotEqual(subprocess.run([tmux, "-L", socket, "has-session"],
                                               capture_output=True).returncode, 0)
            socket_dir = Path(os.environ.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{os.getuid()}"
            self.assertFalse((socket_dir / socket).exists())
            self.assertEqual(subprocess.run([tmux, "-L", other, "has-session"],
                                            capture_output=True).returncode, 0)
        finally:
            subprocess.run([tmux, "-L", socket, "kill-server"], capture_output=True)
            subprocess.run([tmux, "-L", other, "kill-server"], capture_output=True)
            (Path(os.environ.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{os.getuid()}" / other).unlink(missing_ok=True)

    @unittest.skipUnless(shutil.which("tmux") and hasattr(os, "getuid"), "tmux is optional")
    def test_private_tmux_pane_reports_codex_exit_status(self) -> None:
        tmux = shutil.which("tmux")
        for expected in (0, 9):
            socket = f"llmbench-exit-test-{uuid.uuid4().hex[:10]}"
            try:
                subprocess.run([tmux, "-L", socket, "-f", str(tui.TMUX_CONFIG), "new-session",
                                "-d", "-s", "agent", "--", f"sh -c 'exit {expected}'"], check=True)
                for _ in range(20):
                    state, code = tui.BenchmarkApp.tmux_pane_state(tmux, socket)
                    if state == "dead":
                        break
                    time.sleep(0.01)
                self.assertEqual((state, code), ("dead", expected))
            finally:
                subprocess.run([tmux, "-L", socket, "kill-server"], capture_output=True)
                (Path(os.environ.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{os.getuid()}" / socket).unlink(missing_ok=True)

    def test_embedded_suite_preflight_and_exit(self) -> None:
        created = []
        real_terminal = Terminal
        patches = [
            patch.object(tui, "migrate_old_files", lambda: None),
            patch.object(tui, "create_suite", lambda *args: created.append(args)),
            patch.object(tui, "show_suite", lambda _id: {"suite": {"status": "frozen"}}),
            patch.object(tui.BenchmarkApp, "embedded_terminal_available", lambda _self: True),
            patch.object(tui, "embedded_codex_command", lambda prompt: (["codex"], None)),
            patch.object(tui, "CodexTerminal", lambda command, id: real_terminal(
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

    def test_hover_typing_filters_both_pickers_without_losing_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            first = tui_data.save_model({"artifact": "/tmp/model-alpha.gguf", "label": "Alpha"}, db)
            second = tui_data.save_model({"artifact": "/tmp/model-beta.gguf", "label": "Beta"}, db)
            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui, "latest_request", lambda kind: tui_data.latest_request(kind, db)),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 40)) as pilot:
                        self.assertEqual(app.query_one("#engine-list").styles.height.value, 17)
                        self.assertEqual(app.query_one("#model-list").styles.height.value, 17)
                        app.query(TabbedContent).first().active = "models"
                        await pilot.pause()
                        picker = app.query_one("#model-list", SelectionList)
                        picker.select(first)
                        await pilot.pause()
                        await pilot.hover("#model-list", offset=(5, 3))
                        await pilot.press("b", "e")
                        self.assertEqual([x.value for x in picker.options], [second])
                        self.assertIn(first, app.selected("#model-list"))
                        await pilot.press("escape")
                        self.assertEqual(len(picker.options), 2)
                        self.assertIn(first, picker.selected)
                        await pilot.press("q")
                        self.assertEqual(app.picker_filters["model"], "q")
                        await pilot.press("escape")
                        app.query(TabbedContent).first().active = "engines"
                        await pilot.pause()
                        await pilot.hover("#engine-filter")
                        await pilot.hover("#engine-list", offset=(5, 3))
                        app.query_one("#engine-list").focus()
                        await pilot.press("u", "p")
                        self.assertEqual([x.value for x in app.query_one("#engine-list").options], ["upstream"])

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_right_click_edits_row_and_escape_restores_add_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            first = tui_data.save_model({"artifact": "/tmp/alpha.gguf", "label": "Alpha"}, db)
            second = tui_data.save_model({"artifact": "/tmp/beta.gguf", "label": "Beta"}, db)
            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
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
                    async with app.run_test(size=(100, 40)) as pilot:
                        app.query(TabbedContent).first().active = "models"
                        await pilot.pause()
                        await pilot.click("#model-list", offset=(5, 2), button=3)
                        self.assertEqual(app.edit_model_id, second)
                        self.assertEqual(app.mode["model"], "manual")
                        self.assertEqual(app.query_one("#model-label", Input).value, "Beta")
                        self.assertNotIn(second, app.selected("#model-list"))
                        self.assertEqual(str(app.query_one("#model-save").label), "Update model")
                        app.query_one("#model-label", Input).value = "Beta updated"
                        app.save_model()
                        self.assertEqual(len(tui_data.list_models(db)), 2)
                        self.assertEqual(next(x for x in tui_data.list_models(db) if x["id"] == second)["label"], "Beta updated")
                        app.query_one("#model-label", Input).focus()
                        await pilot.press("escape")
                        self.assertIsNone(app.edit_model_id)
                        self.assertEqual(str(app.query_one("#model-save").label), "Add model")
                        app.query_one("#model-label", Input).value = "Gamma"
                        app.query_one("#model-artifact", Input).value = "/tmp/gamma.gguf"
                        app.save_model()
                        self.assertEqual(len(tui_data.list_models(db)), 3)
                        self.assertTrue(any(x["id"] == first for x in tui_data.list_models(db)))


                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 40)) as pilot:
                        await pilot.click("#engine-list", offset=(5, 2), button=3)
                        self.assertEqual(app.edit_engine_id, "leloch-v1")
                        self.assertEqual(app.mode["engine"], "manual")
                        self.assertEqual(app.query_one("#engine-revision", Input).value,
                                         next(x for x in app.engines if x["id"] == "leloch-v1")["revision"])
                        self.assertNotIn("leloch-v1", app.selected("#engine-list"))
                        app.action_clear_edit()
                        self.assertIsNone(app.edit_engine_id)

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_left_click_toggles_engine_and_model_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            model = tui_data.save_model({"artifact": "/tmp/demo.gguf", "label": "Demo"}, db)
            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui, "latest_request", lambda kind: tui_data.latest_request(kind, db)),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 40)) as pilot:
                        picker = app.query_one("#engine-list", SelectionList)
                        ident = picker.get_option_at_index(1).value
                        self.assertNotIn(ident, app.selected("#engine-list"))
                        await pilot.click("#engine-list", offset=(5, 2), button=1)
                        self.assertIn(ident, app.selected("#engine-list"))
                        await pilot.click("#engine-list", offset=(5, 2), button=1)
                        self.assertNotIn(ident, app.selected("#engine-list"))

                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 40)) as pilot:
                        app.query(TabbedContent).first().active = "models"
                        await pilot.pause()
                        await pilot.click("#model-list", offset=(5, 1), button=1)
                        self.assertIn(model, app.selected("#model-list"))
                        await pilot.click("#model-list", offset=(5, 1), button=1)
                        self.assertNotIn(model, app.selected("#model-list"))

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_suite_create_open_and_delete_in_tui(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "catalog.sqlite3"
            engine = tui_data.save_engine({"label": "Demo", "type": "git",
                                           "locator": "https://example.org/demo.git"}, db)
            model = tui_data.save_model({"artifact": "/tmp/demo.gguf", "label": "Demo"}, db)
            patches = [
                patch.object(tui, "migrate_old_files", lambda: None),
                patch.object(tui, "list_engines", lambda: tui_data.list_engines(db)),
                patch.object(tui, "list_models", lambda: tui_data.list_models(db)),
                patch.object(tui, "load_state", lambda: tui_data.load_state(db)),
                patch.object(tui, "save_state", lambda state: tui_data.save_state(state, db)),
                patch.object(tui, "latest_request", lambda kind: tui_data.latest_request(kind, db)),
                patch.object(tui, "list_suites", lambda: suite_store.list_suites(db)),
                patch.object(tui, "show_suite", lambda ident: suite_store.show_suite(ident, db)),
                patch.object(tui, "create_suite", lambda ident, engines, models, updates:
                             suite_store.create_suite(ident, engines, models, updates, db)),
                patch.object(tui, "delete_suite", lambda ident: suite_store.delete_suite(ident, db)),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 40)) as pilot:
                        app.query_one("#engine-list", SelectionList).select(engine)
                        app.query_one("#model-list", SelectionList).select(model)
                        app.query_one("#suite-id", Input).value = "demo-suite"
                        app.save_suite_draft()
                        self.assertEqual([x["id"] for x in suite_store.list_suites(db)], ["demo-suite"])
                        picker = app.query_one("#suite-list", OptionList)
                        self.assertEqual(picker.styles.height.value, 3)
                        self.assertTrue(app.query_one("#run-setup-empty").display)
                        picker.highlighted = 0
                        app.new_suite()
                        app.query_one("#engine-list", SelectionList).deselect_all()
                        app.query_one("#model-list", SelectionList).deselect_all()
                        app.open_suite()
                        self.assertEqual(app.value("suite-id"), "demo-suite")
                        self.assertEqual(app.selected("#engine-list"), [engine])
                        self.assertEqual(app.selected("#model-list"), [model])
                        app.remove_suite()
                        self.assertEqual(len(suite_store.list_suites(db)), 1)
                        app.remove_suite()
                        self.assertEqual(suite_store.list_suites(db), [])
                        self.assertEqual(app.value("suite-id"), "")
                        await pilot.pause()

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_codex_terminal_wheel_opens_and_scrolls_transcript(self) -> None:
        terminal = tui.CodexTerminal(command=["true"])
        terminal.mouse_mode = "normal"
        event = SimpleNamespace(stop=Mock())
        with patch.object(terminal.board.display, "input_key") as keys:
            terminal.on_mouse_scroll_up(event)
            terminal.on_mouse_scroll_up(event)
            terminal.on_mouse_scroll_down(event)
            self.assertEqual(keys.call_args_list, [
                unittest.mock.call("t", tui.constants.KEY_MOD_CTRL),
                *[unittest.mock.call("up")] * 6,
                *[unittest.mock.call("down")] * 3,
            ])
            self.assertEqual(event.stop.call_count, 3)
            self.assertTrue(terminal.transcript_open)

    def test_tmux_is_optional_and_command_keeps_prompt_literal(self) -> None:
        prompt = "Benchmark user's model; echo should-not-run"
        with patch.object(tui.shutil, "which", return_value=None):
            command, socket = tui.embedded_codex_command(prompt)
        self.assertIsNone(socket)
        self.assertEqual(command[-1], prompt)
        self.assertIn("--no-alt-screen", command)
        with patch.object(tui.shutil, "which", return_value="/usr/bin/tmux"):
            command, socket = tui.embedded_codex_command(prompt)
        self.assertTrue(socket.startswith("llmbench-"))
        self.assertEqual(command[0], "/usr/bin/tmux")
        self.assertEqual(command[command.index("--") + 1], shlex.join([
            "codex", "--no-daemon", "--no-alt-screen", "-C", str(tui.ROOT), prompt]))


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
            with self.assertRaisesRegex(ValueError, "Freeze"):
                suite_store.finish_preparation("demo-suite", "Too early", db)
            suite_store.freeze_suite("demo-suite", db)
            self.assertEqual(suite_store.show_suite("demo-suite", db)["suite"]["status"], "frozen")
            suite_store.finish_preparation("demo-suite", "Reviewed frozen handoff", db)
            self.assertEqual(suite_store.preparation_signal("demo-suite", db)["message"], "Reviewed frozen handoff")
            with self.assertRaisesRegex(ValueError, "frozen"):
                suite_store.record_engine("demo-suite", engine, head, db)
            artifact.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                suite_store.validate_suite("demo-suite", db)

    def test_agent_prompt_uses_validated_storage(self) -> None:
        prompt = make_prompt("prepare", "demo-suite", ["engine"], ["model"], False)
        self.assertIn("suite_store.py freeze demo-suite", prompt)
        self.assertIn("do not claim the plan is frozen", prompt)
        self.assertIn("finish-prepare demo-suite", prompt)
        self.assertNotIn("finish-prepare", make_prompt("run", "demo-suite", ["engine"], ["model"], False))

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
