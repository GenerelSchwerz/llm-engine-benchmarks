"""Results stay discoverable and agent findings must pass validation."""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import OptionList, RichLog, TabbedContent

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import results_store  # noqa: E402
import tui  # noqa: E402


class ResultsTest(unittest.TestCase):
    def test_legacy_run_is_indexed_and_qualified_summary_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "results" / "demo" / "run-old"
            directory.mkdir(parents=True)
            (directory / "run-summary.json").write_text(json.dumps({"result": "old failure"}))
            (directory / "benchy-qualified-summary.json").write_text(json.dumps({
                "benchy_status": "complete", "runs": [{"status": "complete", "engine": "e",
                "arm": "baseline", "concurrency": 1,
                "shapes": [{"depth": 0, "decode_tps_median": 42.5}]}],
                "qualified_limitations": ["Output was not quality matched"],
            }))
            rows = results_store.list_results(root)
            self.assertEqual(rows[0]["key"], "demo/run-old")
            self.assertEqual(rows[0]["status"], "complete")
            pulled = results_store.pull_findings("demo/run-old", root)
            self.assertEqual(pulled["source"], "benchy-qualified-summary.json")
            self.assertIn("42.50", pulled["highlights"][0])
            self.assertEqual(pulled["limitations"], ["Output was not quality matched"])

    def test_reviewed_findings_validate_paths_and_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "results" / "demo" / "run-1"
            directory.mkdir(parents=True)
            (directory / "evidence.json").write_text("{}")
            data = {"summary": "Measured locally", "highlights": ["42 tok/s"],
                    "limitations": ["No final answer"], "artifacts": ["evidence.json"]}
            saved = results_store.record_findings("demo/run-1", data, root)
            self.assertTrue(saved.is_file())
            self.assertEqual(results_store.pull_findings("demo/run-1", root)["source"],
                             "reviewed findings")
            with self.assertRaises(ValueError):
                results_store.record_findings("demo/run-1", {**data, "artifacts": ["../secret"]}, root)
            with self.assertRaises(ValueError):
                results_store.record_findings("../demo/run-1", data, root)

    def test_results_tab_selects_run_and_shows_findings(self) -> None:
        row = {"key": "demo/run-1", "status": "complete", "summary_file": "qualified.json", "mtime": 1}
        result = {"key": row["key"], "directory": "/tmp/results/demo/run-1",
                  "summary_file": "qualified.json", "summary": {}, "findings_saved": False}
        findings = {"source": "qualified.json", "summary": "One configuration complete",
                    "highlights": ["42 tok/s"], "limitations": ["Observational"],
                    "artifacts": ["qualified.json"]}
        async def exercise():
            app = tui.BenchmarkApp()
            async with app.run_test(size=(110, 40)) as pilot:
                app.query_one("#main-tabs", TabbedContent).active = "results"
                self.assertEqual(app.query_one("#result-list", OptionList).highlighted, 0)
                self.assertEqual(app.highlighted_result(), "demo/run-1")
                app.show_findings()
                await pilot.pause()
                self.assertTrue(app.query_one("#result-findings", RichLog).lines)
        with patch.object(tui, "list_results", return_value=[row]), \
             patch.object(tui, "show_result", return_value=result), \
             patch.object(tui, "pull_findings", return_value=findings):
            asyncio.run(exercise())

    def test_talk_opens_selected_run_review_without_launching_measurements(self) -> None:
        row = {"key": "demo/run-1", "status": "complete", "summary_file": "qualified.json", "mtime": 1}
        result = {"key": row["key"], "directory": "/tmp/results/demo/run-1",
                  "summary_file": "qualified.json", "summary": {}, "findings_saved": False}
        prompts = []
        async def exercise():
            app = tui.BenchmarkApp()
            async with app.run_test(size=(110, 40)):
                app.query_one("#main-tabs", TabbedContent).active = "results"
                self.assertFalse(app.query("#result-question"))
                await app.start_results_agent("demo/run-1")
                self.assertEqual(app.query_one("#main-tabs", TabbedContent).active, "agents")
                self.assertEqual(len(prompts), 1)
                self.assertIn("Start with a concise review", prompts[0])
                self.assertIn("record-findings demo/run-1", prompts[0])
                self.assertIn("Do not rerun benchmarks", prompts[0])
        with patch.object(tui, "list_results", return_value=[row]), \
             patch.object(tui, "show_result", return_value=result), \
             patch.object(tui.BenchmarkApp, "embedded_terminal_available", return_value=False), \
             patch.object(tui.BenchmarkApp, "run_results_agent",
                          lambda _self, _key, prompt, _log: prompts.append(prompt)):
            asyncio.run(exercise())

    def test_close_selected_agent_removes_its_pane(self) -> None:
        row = {"key": "demo/run-1", "status": "complete", "summary_file": "qualified.json", "mtime": 1}
        result = {"key": row["key"], "directory": "/tmp/results/demo/run-1",
                  "summary_file": "qualified.json", "summary": {}, "findings_saved": False}
        async def exercise():
            app = tui.BenchmarkApp()
            async with app.run_test(size=(110, 40)) as pilot:
                await app.start_results_agent("demo/run-1")
                tabs = app.query_one("#agent-tabs", TabbedContent)
                pane_id = tabs.active
                self.assertNotEqual(pane_id, "agent-overview")
                self.assertFalse(app.query("#agent-close"))
                log_id = next(iter(tabs.query_one(f"#{pane_id}").query(RichLog))).id
                class Process:
                    stopped = False
                    def poll(self):
                        return None
                    def terminate(self):
                        self.stopped = True
                process = Process()
                app.background_processes[log_id] = process
                await pilot.press("f4")
                await pilot.pause()
                self.assertTrue(process.stopped)
                self.assertFalse(app.query(f"#{pane_id}"))
                self.assertEqual(tabs.active, "agent-overview")
        with patch.object(tui, "list_results", return_value=[row]), \
             patch.object(tui, "show_result", return_value=result), \
             patch.object(tui.BenchmarkApp, "embedded_terminal_available", return_value=False), \
             patch.object(tui.BenchmarkApp, "run_results_agent", lambda *_args: None):
            asyncio.run(exercise())

    def test_close_live_terminal_clears_tracking(self) -> None:
        row = {"key": "demo/run-1", "status": "complete", "summary_file": "qualified.json", "mtime": 1}
        result = {"key": row["key"], "directory": "/tmp/results/demo/run-1",
                  "summary_file": "qualified.json", "summary": {}, "findings_saved": False}
        async def exercise():
            app = tui.BenchmarkApp()
            async with app.run_test(size=(110, 40)):
                await app.start_results_agent("demo/run-1")
                tabs = app.query_one("#agent-tabs", TabbedContent)
                pane_id = tabs.active
                self.assertEqual(len(app.terminals), 1)
                await app.close_selected_agent()
                self.assertFalse(app.terminals)
                self.assertFalse(app.query(f"#{pane_id}"))
        with patch.object(tui, "list_results", return_value=[row]), \
             patch.object(tui, "show_result", return_value=result), \
             patch.object(tui.BenchmarkApp, "embedded_terminal_available", return_value=True), \
             patch.object(tui, "embedded_codex_command",
                          return_value=(["sh", "-c", "sleep 30"], None)):
            asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
