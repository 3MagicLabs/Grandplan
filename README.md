# grandplan

> A native **Windows, fully-offline** "second brain": select text in *any* app → capture it with a
> global hotkey → a **local LLM** organizes it into a clean, atomic note (your original preserved
> **verbatim**) → you approve → it's written as a well-linked, de-duplicated Markdown note into your
> **Obsidian vault**, and projects into an **actionable plan**.

**Status:** planning complete → starting Phase 0 (gated core). Nothing leaves your machine.

## Why

Notes are scattered across email, Notepad, Docs, paper, and phones. Existing tools either make you
organize manually or only *search* what you already wrote. grandplan captures from anywhere, organizes
losslessly with local AI, and keeps a **clean, connected** vault — never a second jumbled mess.

See **[SPEC.md](./SPEC.md)** (requirements) and **[RESEARCH.md](./RESEARCH.md)** (prior art, techniques,
feasibility) for the full picture, and **[docs/adr/](./docs/adr/)** for architecture decisions.

## Architecture (ports & adapters)

A platform-agnostic **core** (segment · preserve-verbatim · organize · embed · link · dedup · project)
depends only on **ports** (`Capturer`, `Organizer`, `Embedder`, `Repository`, `VaultWriter`, `Planner`).
Windows-only **adapters** (global-hotkey capture, local LLM runtime, the Obsidian vault) implement those
ports. The core is fully unit-testable and is the part the quality gate governs.

- **Core** — pure Python, no Windows/LLM/UI deps. Developed & gated here (works under WSL2).
- **Adapters** — thin Windows implementations; integration-tested on Windows.
- **Store** — the Obsidian vault (Markdown, source of truth) + an internal SQLite index (embeddings, edges).

## Constraints (non-negotiable)

- **Offline only** — zero network egress.
- **Lossless** — every original captured selection is preserved byte-for-byte; never mutated.
- **Modest hardware** — runs on a 16GB-RAM machine, no dedicated GPU.

## Quality gate (borromeo)

This repo is governed by [borromeo](https://github.com/3MagicLabs/borromeo). Nothing is "done" until the
gate is green. Run it locally:

```bash
/path/to/borromeo/verify.sh        # build · hygiene · format · lint · typecheck · test+coverage · security
```

CI (`.github/workflows/ci.yml`) **mirrors** the borromeo gate so pull requests are checked automatically.

## Development

- Dev/test the **core** in this Linux/WSL2 environment (Python + ruff/mypy/pytest/bandit).
- The **Windows adapters** (capture, GUI, LLM runtime) run/integration-test on Windows.
- Reproducible test image: `docker build -t grandplan-dev . && docker run --rm grandplan-dev`.

See **[CONTRIBUTING.md](./CONTRIBUTING.md)**.

## License

[MIT](./LICENSE).
