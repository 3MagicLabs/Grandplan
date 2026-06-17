# Running grandplan on Windows & building the remaining adapters

The fully-offline **core** is implemented, runnable, and gated (see the README and CHANGELOG).
What remains is **Windows-only** and needs this machine to build and verify:

- **#6** — global-hotkey + clipboard/UIA capture (`Capturer`)
- **#7** — the PySide6 review/approve GUI

Both implement (or drive) existing core ports, so the gated core does not change.

## ⚠ Run the capture/GUI on native Windows — not inside WSL2

The capture/GUI **and the local LLM** are meant to run on **native Windows**. Running them **inside
WSL2** is a documented hard-crash path (ADR-0006): WSL2 is a VM that, **with no memory cap**, can grow
to consume nearly all host RAM. A local 7B model (~5 GB) + transformer embeddings (~2 GB) loaded in
that VM on a 16 GB laptop exhausts memory → the WSL VM is torn down (**all your WSL shells disconnect
at once**), the Windows host freezes, and the network stalls.

If you run anything heavy under WSL2 anyway, **cap the VM's memory first** as a backstop. Create
`C:\Users\<you>\.wslconfig`:

```ini
[wsl2]
memory=8GB      # hard cap so WSL can never starve Windows
swap=2GB
processors=4
```

then run `wsl --shutdown` in PowerShell and reopen WSL. The capture serialization in ADR-0006 already
prevents stacked/parallel model loads; this cap bounds the blast radius even if something else misbehaves.

## 1. Prerequisites

- **Python 3.10+** (3.12 recommended) — <https://www.python.org/downloads/windows/>
- **Git** — <https://git-scm.com/download/win>
- *(For real local AI)* **Ollama for Windows** — <https://ollama.com/download>, then pull the default model:
  ```cmd
  ollama pull llama3.2:3b
  ```
  `llama3.2:3b` (~2 GB) is the default — sized for the project's "16 GB RAM, no GPU" constraint. On a
  machine with more headroom, pull a stronger model and pass `--model` (e.g. `ollama pull qwen2.5:7b`
  then `--model qwen2.5:7b` (~5 GB), or `gemma2:9b`). Ollama serves a local API at
  `http://localhost:11434` and runs **offline** once the model is pulled.

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

Use the **real** local AI from the CLI:

```cmd
python -m grandplan organize your-notes.txt -o my-vault --llm --embeddings
```

- `--llm` organizes with a local Ollama model (falls back to the offline baseline if Ollama isn't running).
- `--embeddings` uses local sentence-transformer embeddings (needs the `embeddings` extra installed).
- `--model NAME` selects the Ollama model (default `llama3.2:3b`; e.g. `--model qwen2.5:7b` or `--model gemma2:9b` on machines with more RAM).

Launch the **tray app** (after `pip install -e ".[windows,gui,llm,embeddings]"`):

```cmd
python -m grandplan gui -o my-vault --llm --embeddings
```

A tray icon appears; press the hotkey (`Ctrl+Alt+G`) or use "Capture now" — grandplan grabs your
current selection, shows a review dialog, and on **Save** writes the note into `my-vault`.

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

- ✅ Offline core + CLI + local-AI adapters + capture adapter + review view-model + tray-GUI
  scaffold — all gated (302 tests). The full app is structurally complete.
- ⏳ **Final step (here on Windows):** install `grandplan[windows,gui,llm,embeddings]` + Ollama, run
  `python -m grandplan gui -o my-vault --llm --embeddings`, and verify the
  hotkey → capture → review → save flow end-to-end — tuning the Qt wiring / hotkey as needed (#7).
