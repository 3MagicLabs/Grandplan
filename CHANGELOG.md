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

### Changed (connected-vault & enhancement milestone)
- **Windows-runtime fixes:** create `<vault>/.grandplan/` on first capture (was a `FileNotFoundError`);
  the GUI fails cleanly / degrades on missing optional deps instead of crashing the tray.
- **Resolvable links (US-5):** wikilinks render as `[[<slug>-<id>|<title>]]` and notes carry
  `aliases: ["<id>"]` — no more dangling phantom nodes in the Obsidian graph.
- **Clean frontmatter (US-7):** flattened `source_app/title/uri` scalars (Obsidian renders them
  cleanly instead of a raw JSON-object string).
- **Rehydrating index (US-5):** `JsonlNoteRepository` persists notes/embeddings/edges to
  `.grandplan/index.jsonl`; the GUI reloads it on startup so captures link against the whole
  vault history, not just the current session.
- **LLM enhances the body (US-3):** the model now summarizes + organizes the body (verbatim
  original preserved in the Source block) with validate-and-retry.
- **Actionable, visual plan (US-7/US-8):** `Plan.md` embeds a Mermaid map (dependencies,
  hierarchy, semantic links); `write_projections` regenerates `Plan.md` + `graph.json` on every
  GUI save. End-to-end offline pipeline test added.

### Fixed (capture stability & observability — ADR-0006)
- **Serialized, bounded captures (no more system crash):** extracted the tray GUI's untestable
  orchestration into a Qt-free, fully unit-tested `CaptureCoordinator`. Captures now run on a single
  background worker drained from a queue capped at one pending; back-to-back hotkeys can no longer
  **re-enter the modal dialog and stack concurrent LLM/embedding pipelines** (the memory blow-up that
  could OOM an uncapped WSL2 VM and freeze the host), nor are they silently coalesced/dropped. Excess
  presses are refused with a visible "busy" notification.
- **Progress visibility (US-7):** the coordinator emits a `CaptureStatus` for every stage
  (`capturing → analyzing → awaiting review → committing → saved/discarded/failed → idle`) to the
  tray tooltip/notifications and the log — no more silent multi-second gap with no feedback.
- **Responsive UI:** all heavy work (LLM, embeddings, vault write, plan/graph re-projection) runs off
  the Qt main thread; only the review dialog and tray updates touch it.
- **Memory-safe default model:** default lowered from `qwen2.5:7b` (~5 GB) to `llama3.2:3b` (~2 GB)
  to honor the "runs on 16 GB RAM, no GPU" constraint; stronger models stay opt-in via `--model`.
- **Visible LLM fallback:** `OllamaOrganizer` now logs a WARNING when an attempt fails (was a silent
  degrade that hid a misconfigured/unreachable Ollama).
- **Faster re-projection:** `Planner` toposort uses a heap (O((V+E) log V)) instead of re-sorting the
  frontier on every pop, so regenerating the plan no longer scales poorly with vault size.
- **WSL2 memory cap** documented as a hard prerequisite (`docs/WINDOWS.md`) — the backstop against a
  runaway VM starving the host.

### Added (knowledge evolution & consistency — US-10 / #12, ADR-0007)
- **Richer reconciliation:** a new note is classified against existing notes as `builds_on` /
  `refines` / `supersedes` / `contradicts` (beyond related/duplicate). Classification is a Strategy
  behind the port — deterministic `SimilarityClassifier` baseline (default; behaviour unchanged) +
  an `LlmRelationshipClassifier` adapter (local Ollama, injected client, similarity fallback).
- **Consistency by projection (lossless preserved):** approved relationships are recorded as typed
  edges; a `supersedes` edge makes the old note drop out of the actionable plan (derived, never
  mutated); a `contradicts` is **never auto-resolved** — both notes kept, a `contradicts` edge added,
  and the new note lands as `needs-review`. `Plan.md` gains a **"⚠ Needs review"** section.
- `commit` generalized to typed `links` + an explicit `status`; the CLI/GUI review path wires through.

### Added (hardening & onboarding)
- **QAS-1 offline-egress check (was missing):** an automated test forbids any non-loopback socket
  for a full offline run and proves the guard works (negative control) — the offline guarantee is
  now verified, not just asserted in prose.
- **Vault-clobber safety:** `write_projections` never overwrites a `Plan.md`/`graph.json` it didn't
  generate — a foreign file is preserved and output is diverted to a `.grandplan` sibling (+warning),
  so pointing grandplan at a real Obsidian vault can't destroy a hand-written plan.
- **US-9 portability verified:** a test asserts the JSON graph is an open format (stdlib-parseable,
  documented node/typed-edge schema, no proprietary objects).
- **Windows onboarding:** `docs/QUICKSTART-WINDOWS.md` + a `run.bat` launcher for the daily run.

### Fixed & improved (post-stabilization polish)
- **GUI capture crash fixed (#39):** `_ReviewRequest` made identity-hashable — the worker's
  pending-review set raised `TypeError` on the first real Windows capture (a `pragma: no cover` gap).
- **Clean vault output (#40):** title-based note filenames (the content id moved to frontmatter +
  `aliases`; links resolve via the id alias, independent of the filename, and never clobber a
  different note); Obsidian-valid sanitized tags; richer frontmatter (`due`/`contexts`/`collections`).
- **Index out of the synced vault (#41):** the internal index + verbatim inbox now live under the
  user's home (per-vault, `GRANDPLAN_HOME`-overridable) with one-time non-destructive migration, so a
  OneDrive/Dropbox vault no longer syncs/conflicts grandplan's rebuildable internal state.
- **Richer connections (GUI):** under `--llm`, an `LlmRelationshipClassifier` now classifies the
  **top-k most-similar** candidates into builds_on/refines/supersedes/contradicts (two-tier with the
  cosine baseline for the tail), wired into the tray GUI — bounding LLM calls per capture.

### Notes
- The full **MVP app is structurally complete and gated** (302 tests, green gate + CI): capture →
  organize (baseline or local LLM) → review/approve → linked, de-duplicated Markdown vault → Plan.md.
- **Final step is runtime verification on Windows**: install `grandplan[windows,gui,llm,embeddings]`
  + Ollama, run `python -m grandplan gui -o my-vault --llm --embeddings`, and confirm the
  hotkey → capture → review → save flow, tuning the Qt wiring as needed.
