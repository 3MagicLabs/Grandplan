# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added
- Project planning spine: `SPEC.md` (requirements), `RESEARCH.md` (prior art / techniques / feasibility).
- Repository hygiene: README, LICENSE (MIT), `.gitignore`, `.gitattributes`, CONTRIBUTING, ADRs.
- CI mirroring the borromeo quality gate; Dockerfile for a reproducible core test environment.
- borromeo governance (`borromeo.toml`) — deterministic build/hygiene/format/lint/typecheck/test/security gate.
- Planning model (SPEC §11, ADR-0004/0005): one append-only graph; plans/masterplan/decks as projections;
  horizons, entities, deadlines, contexts; Reconciler (build-on/refine/supersede/contradict-flag);
  workspaces + capability plugins; multi-medium renderers — MVP slice vs deferred phases made explicit.
- Phase-0 core (offline, deterministic, gated): lossless `Original` store (byte-exact round-trip);
  `Note`/`Edge` model + ports; `HeuristicOrganizer` + `HashingEmbedder` baselines; capture pipeline
  (propose/assess/commit with approval + discard); `MarkdownVaultWriter` + JSON graph; embedding-based
  linking + dedup `Reconciler`; `Planner` → `Plan.md`.
- Runnable CLI: `python -m grandplan organize <file> -o <vault>` → vault + `graph.json` + `Plan.md`, offline.
- Local-AI adapters (optional extras `grandplan[llm]` / `grandplan[embeddings]`): `OllamaOrganizer`
  (local-LLM metadata, verbatim body, heuristic fallback) and `SentenceTransformerEmbedder` — drop-in
  behind the ports; real model calls integration-verified on Windows/Ollama.
- CLI `--llm` / `--embeddings` / `--model` flags wire the real adapters into `grandplan organize`.
- Windows selection capture: `Capturer` port + `ClipboardCapturer` (UIA-first, else clipboard
  save/Ctrl+C/restore); real backend in `grandplan[windows]`.
- Review view-model (`app.review`: start_review / approve / discard) — the UI-free, tested controller.
- PySide6 tray GUI (`app.gui.run_app`) + `grandplan gui` subcommand: hotkey → capture → review →
  Save/Discard, bound to the view-model (Qt code is a scaffold, verified on Windows).

### Notes
- The full **MVP app is structurally complete and gated** (278 tests, green gate + CI): capture →
  organize (baseline or local LLM) → review/approve → linked, de-duplicated Markdown vault → Plan.md.
- **Final step is runtime verification on Windows**: install `grandplan[windows,gui,llm,embeddings]`
  + Ollama, run `python -m grandplan gui -o my-vault --llm --embeddings`, and confirm the
  hotkey → capture → review → save flow, tuning the Qt wiring as needed.
