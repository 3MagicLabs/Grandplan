# Running grandplan on Windows & building the remaining adapters

The fully-offline **core** is implemented, runnable, and gated (see the README and CHANGELOG).
What remains is **Windows-only** and needs this machine to build and verify:

- **#6** — global-hotkey + clipboard/UIA capture (`Capturer`)
- **#7** — the PySide6 review/approve GUI

Both implement (or drive) existing core ports, so the gated core does not change.

## 1. Prerequisites

- **Python 3.10+** (3.12 recommended) — <https://www.python.org/downloads/windows/>
- **Git** — <https://git-scm.com/download/win>
- *(For real local AI)* **Ollama for Windows** — <https://ollama.com/download>, then pull a small model:
  ```cmd
  ollama pull llama3.2:3b
  ```
  Ollama serves a local API at `http://localhost:11434` and runs **offline** once the model is pulled.

## 2. Get the code and install

```cmd
git clone https://github.com/3MagicLabs/grandplan.git
cd grandplan
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[llm,embeddings]"
pip install ruff mypy pytest pytest-cov bandit
```

> The embedding model (`all-MiniLM-L6-v2`) downloads once on first use, then runs offline.

## 3. Run the quality gate (mirrors CI)

```cmd
ruff format --check .
ruff check .
python -m compileall -q src
mypy src
pytest -q --cov
bandit -q -r src
```

All must pass — this is exactly what CI runs. For the full borromeo gate, optionally clone
<https://github.com/3MagicLabs/borromeo> and run `borromeo/verify.sh` from Git Bash or WSL.

## 4. Run it

```cmd
python -m grandplan organize your-notes.txt -o my-vault
```

Open `my-vault` as an Obsidian vault to see the graph; `Plan.md` is the generated plan.

Using the **real** local AI today is programmatic (the CLI defaults to the offline baselines):

```python
from grandplan.adapters.ollama_organizer import OllamaOrganizer
from grandplan.adapters.st_embedder import SentenceTransformerEmbedder
# pass these into grandplan.core.pipeline.propose/assess instead of the baselines
```

*(Want `--llm` / `--embeddings` flags on the CLI? It's a small, gateable change — just ask.)*

## 5. Building the remaining adapters (design is ready)

### Capture — issue #6 (`Capturer` port)

Proposed port (add to `grandplan/core/ports.py`):
```python
class Capturer(Protocol):
    def capture(self) -> str | None: ...   # current selection, or None if nothing/!text
```
Windows adapter (`grandplan/adapters/win_capture.py`):
- Global hotkey via `pynput.keyboard.GlobalHotKeys` (background thread) or the `keyboard` lib.
- On trigger: **save** the current clipboard, send `Ctrl+C`, read the selection, **restore** the
  prior clipboard (so we never clobber it). Prefer Windows UI Automation
  (`ITextProvider::GetSelection` via `uiautomation`/`comtypes`) where available; fall back to clipboard.
- Feed the captured text into `pipeline.propose(...)`.
- **Testable here (mock the backend):** save/restore correctness, UIA→clipboard fallback, empty-selection → None.

### Review/approve GUI — issue #7 (drives `assess` → `commit`)

- PySide6 tray app (`QSystemTrayIcon`) + a small dialog showing the captured **original** beside the
  proposed note (title/type/tags), the `ReconcileProposal` ("duplicate of / related to"), and
  **Approve** (→ `commit`) / **Discard** (→ nothing written, US-4). The graph view stays in Obsidian (ADR-0002).
- **Testable here:** the view-model mapping `Assessment`/`ProposedNote` → display, and the
  approve/discard decision wiring. Qt widgets themselves are integration-tested on Windows.

## Status

- ✅ Offline core complete, runnable, gated (265 tests): lossless store · pipeline · vault+graph ·
  linking/dedup · planner · CLI.
- ✅ Local-AI adapters (Ollama, sentence-transformers) behind the ports.
- ⏳ Windows capture (**#6**) and GUI (**#7**) — build here with real verification.
