# LLM Engine Benchmarks

**Compare LLM inference engines with reproducible runs and inspectable evidence.** Bring a source build, package, container, local binary, or remote service. This project gives you a common process without requiring engines to share a codebase, model format, or hardware backend.

The suite records exact versions, model artifacts, commands, prompts, outputs, timing, and memory use. It checks generated text alongside throughput, so a fast but broken run stays visible.

## Installation

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git, then clone the repository:

```sh
git clone https://github.com/GenerelSchwerz/llm-engine-benchmarks.git
cd llm-engine-benchmarks
uv sync
uv run llama-benchy --version
```

`uv sync` installs the TUI and benchmark client from `uv.lock`. It does not install any LLM engine, model weights, or the optional Codex CLI.

## Set up a suite

```sh
uv run scripts/tui.py
```

The minimal terminal UI has four tabs:

| Tab | What you do |
| --- | --- |
| **Engines** | Ask an agent to find and install a fork in one sentence, or toggle to a manual locator form. |
| **Models** | Ask an agent to find or install one or several models, or toggle to a manual locator form. |
| **Suite** | Save a draft, open an existing suite, or delete its catalog plan. Prepare a reviewed plan, then run it. |
| **Agents** | Use Codex inside a separate terminal pane for each running agent. Monochrome terminals show a readable event log instead. |

Use **Tab** to move between controls and **Space** to toggle a selection. Hover over either picker and type to filter; **Backspace** edits the filter and **Esc** clears it. Hidden selections stay selected. Right-click a saved engine or model to edit it; **Esc** returns the form to Add mode. The setup mode button is at the bottom of each tab. In Agent mode, describe what you want and open **Agents**. Color terminals embed the interactive Codex TUI; press **Ctrl+G** to leave its pane. Scroll up over Codex to open its transcript, then scroll through earlier output, or use the **Transcript** button. Monochrome terminals and sessions with `NO_COLOR` use a readable background event log. The program validates saved results when Codex exits. A confident result appears as **ready** and waits for **Confirm result**; an ambiguous or blocked request appears as **needs_input**, and the same input becomes **Answer & retry**. You can switch to Manual mode at any time.

The Suite tab lists names, status, counts, and preparation state. **New** clears the name field; **Save draft** creates its SQLite record from the current selections. **Open** restores a saved plan and its selections. **Delete** requires a second click and removes only the suite record and plan; engine installs, model files, and benchmark artifacts stay in place. Frozen plans cannot be edited; create another suite to change one.

The agent checks the catalog before installing. You can ask it to use an existing install, update an engine or model, or remove one. It signals completion through the validated CLI, so the result can become ready while its interactive terminal stays open. Removing a custom catalog entry leaves its files in place unless you explicitly ask to uninstall them. Built-in engine definitions stay available; uninstalling one removes its local checkout. See the [agent instructions](AGENTS.md) for the validated commands.

Update checks are off by default. The UI generates IDs and saves additions, requests, and selections in a local SQLite file. You do not need to find SHAs, package versions, or tokenizers. During preparation, the agent researches those details, hashes local artifacts, and submits commands and metadata through a [validated CLI](scripts/suite_store.py). Code rejects incomplete records before it freezes the plan. See [model setups](manifests/models.md).

Preparing or running a suite requires the [Codex CLI](https://developers.openai.com/codex/cli/) to be installed and signed in. The UI does not publish results.

For a manual or scripted workflow, use the same commands directly:

```sh
uv run scripts/install_sources.py                 # list available engines
uv run scripts/install_sources.py --id ENGINE_ID  # install one pinned Git source
uv run scripts/check_sources.py --id ENGINE_ID    # check its local pin
```

The checked-in [source list](manifests/sources.json) contains pinned, reusable examples. Git sources install into ignored local directories; package, container, remote, and local entries provide installation notes instead. New entries added in the TUI stay local until you deliberately add them to the shared source list. See the [source format](manifests/source-schema.md).

Then choose models and workloads in [the suite matrix](manifests/matrix.md), prepare an [engine guide](guides/TEMPLATE.md), and follow [the runbook](RUNBOOK.md). The runbook covers a coherent-text track and a separate [llama-benchy](https://github.com/eugr/llama-benchy) track. Engines without a compatible chat endpoint need an adapter for the latter.

## Run with Codex

With the [Codex CLI](https://developers.openai.com/codex/cli/) installed and signed in, start an interactive agent from this repository:

```sh
uv run scripts/start_codex.py prepare my-suite --engine ENGINE_ID --model MODEL_ID
uv run scripts/start_codex.py prepare my-suite --engine ENGINE_ID --model MODEL_ID --check-updates
uv run scripts/start_codex.py run my-suite
```

`prepare` creates a draft and launches the agent. The agent must pass code validation to freeze it, then record a completion signal that appears in the TUI even while its Codex terminal stays open. A frozen plan is a preparation handoff; `run` checks binaries and output before measuring. Update checks are **off by default** to save time and agent usage; `--no-check-updates` states that choice explicitly. Exact versions must still be resolved for new sources. Review the frozen plan before `run`. Repeat `--engine` and `--model` for more selections. Use `--dry-run` to see the prompt. The launcher does not publish results.

## Explore

| Looking for… | Start here |
| --- | --- |
| The full benchmark process and agent handoff | [Runbook](RUNBOOK.md) |
| Editable engines, models, and the pinned benchmark tool | [Source list](manifests/sources.json) · [source format](manifests/source-schema.md) · [model setups](manifests/models.md) · [tooling](manifests/tooling.md) |
| Existing setup examples | [Engine catalog](manifests/engines.md) · [guides](guides/) |
| Prompts and result fields | [Fixtures](fixtures/README.md) · [result template](manifests/run-template.json) |
| Adding an engine or submitting results | [Contributing](CONTRIBUTING.md) |

The included llama.cpp, FreeToken, and KTransformers guides are **research starting points**, not verified performance results. Engine code, model weights, builds, and raw captures are not shipped here.

For automated work, [AGENTS.md](AGENTS.md) gives agents the workspace rules; the runbook contains the procedure shared by humans and agents. Original project files are [MIT licensed](LICENSE). Third-party engines keep their own licenses.
