# grandplan — Windows quick start

The fast path to running the capture/GUI on **native Windows** (the supported runtime — not WSL2;
see [WINDOWS.md](./WINDOWS.md) for why and for full detail). Run everything in a **Windows terminal**
(Windows Terminal / cmd / PowerShell), not WSL.

## 1. Install prerequisites (one time)

- **Python 3.12** — <https://www.python.org/downloads/windows/> (tick *“Add python.exe to PATH”*).
- **Git** — <https://git-scm.com/download/win>
- **Ollama for Windows** — <https://ollama.com/download>

Verify in a new terminal:

```cmd
python --version
git --version
ollama --version
```

## 2. Set up the project (one time)

> **cmd vs PowerShell:** the blocks below use **cmd.exe** syntax. In **PowerShell**, activate with
> `.venv\Scripts\Activate.ps1` instead of `.venv\Scripts\activate` (if blocked once:
> `Set-ExecutionPolicy -Scope Process RemoteSigned`, then retry).

```cmd
git clone https://github.com/3MagicLabs/grandplan.git
cd grandplan
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[windows,gui,llm,embeddings]"
ollama pull llama3.2:3b
```

> `llama3.2:3b` (~2 GB) is the memory-safe default for a 16 GB / no-GPU machine; swap a bigger
> model in with `--model qwen2.5:7b` if you have the RAM.

## 3. Run it (daily)

Point it at your Obsidian vault. **Quote the path if it has spaces:**

```cmd
.venv\Scripts\activate
python -m grandplan gui -o "C:\Users\<you>\OneDrive\Documents\GrandNotes" --llm --embeddings
```

Or use the bundled launcher (edit `VAULT` at the top of `run.bat`, then just):

```cmd
run.bat
```

A tray icon appears. Select text in **any** app → press **`Ctrl+Alt+G`** → review → **Save**. The
tray tooltip shows live progress (`capturing → analyzing → saved`); a second press while busy is
refused with a "busy" tooltip instead of piling up. Notes + `Plan.md` + `graph.json` land in your
vault and Obsidian live-reloads them.

## Notes

- **First run** downloads the embedding model `all-MiniLM-L6-v2` (~90 MB) once, then runs offline.
- **Ollama must be the Windows app** (serves `http://localhost:11434`), not one running inside WSL.
- Your hand-written `Plan.md`/`graph.json` are never overwritten — grandplan writes a
  `.grandplan` sibling instead if it finds a foreign file by those names.
- A vault inside **OneDrive** is synced to the cloud by OneDrive (the app itself stays offline);
  use a local folder if you want strictly on-device storage.
