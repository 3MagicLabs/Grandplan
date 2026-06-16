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

### Notes
- The full **offline core is implemented, runnable, and gated** (265 tests, green gate + CI).
- Remaining MVP work is **Windows-only** and needs that machine to verify: global-hotkey capture (#6)
  and the PySide6 review/approve GUI (#7).
