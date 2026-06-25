# Contributing to grandplan

## Golden rule

Nothing is "done" until the **borromeo gate is green**. We never weaken or skip a check to pass;
a failure becomes a new check. The verifier is external to the generator.

```bash
/path/to/borromeo/verify.sh        # build · hygiene · format · lint · typecheck · test+coverage · security
```

CI mirrors this gate on every push/PR (`.github/workflows/ci.yml`).

## Setup

```bash
git clone https://github.com/3MagicLabs/Grandplan && cd Grandplan
python -m venv .venv && . .venv/bin/activate
pip install -e ".[llm,embeddings,mcp]"   # core + optional extras; add ,windows,gui on Windows
pytest -q                                 # sanity-check the suite (Linux/WSL2)
```

Please also read **[SECURITY.md](./SECURITY.md)** (how to report vulnerabilities — privately, never a
public issue) and **[CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)** (community expectations).

## Workflow (TDD + spec-driven)

1. Work from **[SPEC.md](./SPEC.md)**. Reference the relevant user story (`US-n`) in commits/PRs.
2. **Write the test first** (RED) — especially the lossless round-trip test for any code touching originals.
3. Implement minimally (GREEN), then refactor. Keep coverage from regressing (borromeo ratchets it).
4. Keep the **core** free of Windows/LLM/UI dependencies — depend only on ports; provide fakes for tests.

## Branching & merging

- `main` is protected by the gate. Do feature work on a branch: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`.
- Merge only when the gate is green. With borromeo: `borromeo/merge.sh [base]` runs the gate, then merges if green.
- Conventional commits: `feat: …`, `fix: …`, `refactor: …`, `docs: …`, `test: …`, `chore: …`, `perf: …`, `ci: …`.

## Dev environment

- The **core** is developed and gated in **Linux/WSL2** (Python 3.12 + ruff, mypy, pytest, bandit).
- The **Windows adapters** (global-hotkey capture, local LLM runtime, Obsidian vault writing) are
  run and integration-tested on **Windows** — they can't run inside headless WSL2.
- Reproducible test image: `docker build -t grandplan-dev . && docker run --rm grandplan-dev`.

## Architecture rules (CS130: information hiding, low coupling)

- New external dependencies sit behind a **port** (interface) so they're swappable and testable.
- Originals are **append-only and never mutated**; derived content is always separable from the original.
- Document non-trivial decisions as an ADR in `docs/adr/`.
