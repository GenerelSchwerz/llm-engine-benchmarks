"""Exercise the manifest editor and suite selection without a live terminal."""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Checkbox, Input, SelectionList

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tui  # noqa: E402
import tui_data  # noqa: E402
from start_codex import make_prompt  # noqa: E402


class TuiTest(unittest.TestCase):
    def test_engine_model_edit_and_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = root / "sources.json"
            models = root / "models.json"
            state = root / "state.json"
            sources.write_text('{"schema_version": 2, "sources": []}\n')

            def load_sources():
                return tui_data.load_sources(sources)

            def save_sources(items):
                return tui_data.save_sources(items, sources)

            def load_models():
                return tui_data.load_models(models, sources)

            def save_models(items):
                return tui_data.save_models(items, models, sources)

            def load_state():
                return json.loads(state.read_text()) if state.exists() else {}

            def save_state(data):
                state.write_text(json.dumps(data))

            patches = [
                patch.object(tui, "load_sources", load_sources),
                patch.object(tui, "save_sources", save_sources),
                patch.object(tui, "load_models", load_models),
                patch.object(tui, "save_models", save_models),
                patch.object(tui, "load_state", load_state),
                patch.object(tui, "save_state", save_state),
            ]
            for item in patches:
                item.start()
            try:
                async def exercise():
                    app = tui.BenchmarkApp()
                    async with app.run_test(size=(100, 35)) as pilot:
                        app.query_one("#engine-id", Input).value = "sample"
                        app.query_one("#engine-locator", Input).value = "sample-package"
                        app.query_one("#engine-ref", Input).value = "pip"
                        app.query_one("#engine-revision", Input).value = "1.2.3"
                        app.query_one("#engine-notes", Input).value = "Install the pinned wheel"
                        app.query_one("#engine-type", tui.Select).value = "package"
                        app.save_engine()
                        assert load_sources()[0]["id"] == "sample"

                        app.query_one("#model-id", Input).value = "sample-model"
                        app.query_one("#model-artifact", Input).value = "/tmp/sample.gguf"
                        app.query_one("#model-context", Input).value = "8192"
                        app.query_one("#model-engines", Input).value = "sample"
                        app.save_model()
                        assert load_models()[0]["engine_ids"] == ["sample"]

                        app.query_one("#engine-list", SelectionList).select("sample")
                        app.query_one("#model-list", SelectionList).select("sample-model")
                        app.query_one("#suite-id", Input).value = "sample-suite"
                        app.query_one("#check-updates", Checkbox).value = True
                        app.remember()
                        assert json.loads(state.read_text()) == {
                            "engines": ["sample"], "models": ["sample-model"],
                            "suite_id": "sample-suite", "check_updates": True,
                        }
                        await pilot.pause()

                asyncio.run(exercise())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_selected_models_reach_agent_prompt(self) -> None:
        prompt = make_prompt("prepare", "sample-suite", ["engine"], ["model"], False)
        self.assertIn("for engine and model", prompt)
        self.assertIn("without checking upstream", prompt)


if __name__ == "__main__":
    unittest.main()
