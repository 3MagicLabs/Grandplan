# Getting started

## Run the offline core (Linux / WSL2 / macOS / Windows)

```bash
git clone https://github.com/3MagicLabs/Grandplan && cd Grandplan
python -m venv .venv && . .venv/bin/activate
pip install -e ".[llm,embeddings,mcp]"
grandplan organize notes.txt -o my-vault    # messy text file -> Obsidian-style vault
```

It splits the file into notes, organizes each (title/type/tags), links related ones, skips
near-duplicates, and writes `my-vault/*.md` + `graph.json` + `Plan.md`. Fully offline; add `--llm` /
`--embeddings` to use a local Ollama model + local embeddings.

## Capture surfaces
- **HTTP intake** — `grandplan serve -o <vault>` (POST `/directive`; binds `127.0.0.1` by default).
- **Folder watch** — `grandplan watch -o <vault> --folder <inbox>`.
- **All at once** — `grandplan up -o <vault>`.

## Windows (real local AI + global-hotkey capture + GUI)
See `docs/WINDOWS.md` and `docs/QUICKSTART-WINDOWS.md` in the repo.

## Contributing
Read `CONTRIBUTING.md`: the borromeo gate must be green (build · format · lint · typecheck ·
test+coverage · security); TDD, conventional commits, feature branches, PR review.
