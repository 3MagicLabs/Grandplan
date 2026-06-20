# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **HTTP directive intake (theme J transport)** — `adapters/http_intake.py` + `grandplan serve`: a
  localhost HTTP endpoint (`POST /directive` with `{content, playbook?, prompt?}`) that enqueues a
  directive — the "send to my agent from my phone" transport. Pure `handle_intake` (auth/validation/
  enqueue) is gated; the socket server is the shell. Binds 127.0.0.1 by default and **refuses a
  routable host without a `--token`** (constant-time bearer check). Offline — only receives + stores.
- **Agent intake — directives + playbooks (theme J)** — `core/directive.py`: an append-only
  `Directive` (content + instruction) an AI agent pulls and fulfils, with reusable named `Playbook`
  presets (built-ins: `profile-and-connect`, `capture-and-file`, `extract-actions`). In-memory +
  JSONL stores (completion is a derived event). Exposed over MCP (`list_directives`/
  `complete_directive`, off until `grandplan mcp --directives`) and via `grandplan directive add|list`.
  The in-house spine for "send content + a prompt to my agent and let it enrich/act" — the agent uses
  the existing write/search tools; networked transport + web research are deferred opt-in connectors.
  See `SPEC-AGENT-INTAKE.md`.
- **Productivity exports (theme B, local/offline)** — `core/export.py`: `to_markdown_tasks` (an
  Obsidian-Tasks/GitHub `- [ ]` checklist with `📅 due` markers + `#tags`) and `to_csv` (one row per
  note). New `grandplan export --format tasks|csv [--out PATH]` command (zero egress).
- **Voice capture seam (offline STT, theme H / "PR-H")** — `adapters/voice.py`: a `VoiceCapturer`
  (conforms to the `Capturer` port) with an injected `Transcriber` backend, so the capture logic
  (silence → None, error → None) is gated offline. The real backend is a local Whisper model + mic
  (`pip install grandplan[voice]`), lazy/optional and fully on-device — no audio leaves the machine.
  GUI hotkey wiring deferred (Windows-only). New `voice` optional extra.
- **Critical-path + parallel-batch scheduling (theme C)** — `core/schedule.py`: `critical_path`
  (the longest chain of still-open dependency-linked tasks — the bottleneck) and `parallel_batches`
  (open tasks grouped by dependency depth — each batch runs concurrently once the prior is done).
  Pure DAG analytics over a `Plan` (skips done prerequisites and cycle notes). Surfaced in the
  Markdown report (shown only when there's a real ≥2-step chain / a parallelizable batch).
- **Markdown report renderer (knowledge → deliverable, theme E)** — `core/render.py`: a `Renderer`
  port + `MarkdownReportRenderer` composing plan + masterplan + timeline + health into one
  self-contained Markdown report (summary, top priorities, blocked, schedule, hierarchy by horizon,
  open questions, graph health). Offline, deterministic, pure. New `grandplan report -o <vault>
  [--out PATH] [--title T]` command (writes `<vault>/report.md`, or `--out -` for stdout).
- **Entity extraction + `involves` edges (agent-operable vault, step 3)** — `core/entities.py`: an
  `EntityExtractor` port + offline `HeuristicEntityExtractor` (multi-word proper nouns, org-suffixed
  names, `@handles`) + `materialize_entities`, turning people/org mentions into `entity` nodes joined
  by `involves` edges so the graph becomes a people/org graph agents can reason over. Append-only +
  idempotent (entity ids content-addressed by name); `entity` nodes are kept out of the masterplan
  roots. Exposed as the `extract_entities` agent-write tool, **and auto-extracted during
  `organize`/`regenerate`** via an Ollama-backed `LlmEntityExtractor` (unioned with the heuristic;
  heuristic-only under `--no-llm` or on any model failure).
- **Agent write tools (agent-operable vault, step 2)** — `core/write.py` `VaultWrite`: an append-only,
  offline write facade letting AI agents enrich/organize/create safely. Five operations —
  `set_status`, `record_edit`, `add_resource`, `place` (typed edge), `propose_note` — each reuses the
  existing PR-A…PR-G event ops (no stored note/original is ever mutated; current state stays derived),
  validates inputs (unknown note / bad enum / self-loop → clear error), and reports `applied=False` on
  an idempotent no-op. Exposed over MCP via `WRITE_TOOLS`/`dispatch_write` and the server's
  `tools_for`/`route` helpers; `grandplan mcp --write` opts in (read-only by default).
  `SPEC-AGENT-VAULT.md` §"Step 2".
- **PR-F trustworthy organization** — the local model is now the **default** organizer/placer for
  `organize`/`gui` (`--no-llm` opts into the offline baseline; `--llm` kept as a no-op). When the
  model is required and unreachable it **fails loud** (`OrganizerUnavailable`) with guidance instead
  of silently emitting keyword output; the verbatim capture is preserved first, so nothing is lost.
- **Diagnostics (QAS-8)** — `core/quality.py` flags un-organized notes (raw/truncated title, verbatim
  body, no tags); `core/report.py` prints a health report on every `organize`/`regenerate` (notes,
  horizons, structural-vs-semantic edges, low-quality + isolated notes, "model likely never ran").
- **`grandplan regenerate`** — rebuild a vault from its lossless inbox originals through the current
  pipeline (heuristic→LLM quality); atomic + fail-safe, backs up the old index to `index.jsonl.bak`.
- **`grandplan doctor`** — read-only health report for an existing vault.
- **PR-G relational organization (keystone)** — a placement stage (`core/placement.py` `Placer` port +
  `HeuristicPlacer`; `adapters/llm_placer.py` `LlmPlacer`) proposes structural `part_of`/`depends_on`
  edges for each new note against the existing graph, wired into the CLI and GUI capture flow. The
  masterplan/plan now get real hierarchy + dependency sequence instead of only similarity links.
  Append-only (edges only; no note mutated); offline (heuristic pure, LLM localhost-only).

- **Completed dependency model + feasible Timeline** — placement now proposes `blocks` and
  `waiting_on` edges (LLM placer) in addition to `part_of`/`depends_on`; the planner treats
  `waiting_on` as a scheduling prerequisite. New `Timeline.md` projection (and `get_timeline` MCP
  tool) orders actionable notes into a feasible schedule — **ready / waiting / scheduled-by-date /
  ⚠ conflicts** (flags a note due before its prerequisite, and dependency cycles).
- **Actionable enhancement** — the LLM organizer now ENHANCES each capture and, for actionable
  notes (task/project/goal), emits a `## Next steps` section with concrete `- [ ]` checklist items
  (RESEARCH §0 "enhance"). QAS-8 gained a check that flags an actionable note with no next-step
  checklist, so the report/doctor surface notes that aren't truly actionable.
- **Agent-operable vault (read) + local MCP server** — `core/query.py` `VaultQuery` exposes the graph
  as JSON (list/get/search notes, plan, masterplan, graph, doctor); `TOOLS`/`dispatch` define + route
  MCP tools (pure, tested). `adapters/mcp_server.py` serves them over **stdio** (`grandplan mcp -o
  <vault>`, optional `mcp` extra) so AI agents can read/distill the vault with **zero egress**.
- **Calendar connector (local, offline)** — `grandplan calendar -o <vault>` exports notes with a
  `due` date to a standards-compliant RFC 5545 `.ics` feed (`grandplan.ics`) any calendar app can
  subscribe to. Zero egress; pure/deterministic (caller-supplied timestamp). `core/calendar.py`.

### Added (earlier)
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

### Added (event-sourced "git for ideas" — ADR-0008)
- **Status event substrate (PR-A, #44):** `index.jsonl` becomes a true event log — a status change
  is an appended `status` event (`set_status`/`status_of` on both repos, idempotent), current status
  is **derived** (last-write-wins), and the Planner/vault/graph all read the derived status so the
  three projections never disagree. The stored note is never mutated (lossless/append-only). Contract:
  `SPEC-PR-B`'s sibling `SPEC-PR-A.md`.
- **Capture-driven status updates (PR-B):** a capture that reports progress ("done: built the
  resume", "started the landing page", "up next …", "reopen …") is recognised as an **update** to the
  relevant existing note, not a new idea. The flow: detect update-intent → match the note by
  embedding similarity → propose the status change in the **same review dialog** → on approval append
  a `status` event and re-project — **no duplicate note, the original never mutated**, the raw capture
  still kept in the inbox. A `done` update makes the task leave "Now" and unblock its dependents.
  - `UpdateDetector` port (Strategy): deterministic `HeuristicUpdateDetector` (word-boundary cue
    matching → DONE/ACTIVE/NEXT, plus `reopen` → ACTIVE) is the offline baseline; an Ollama-backed
    `LlmUpdateDetector` (injected client, JSON-validated, **heuristic fallback** on any failure)
    judges intent under `--llm`. Wired into the tray GUI and the `CaptureCoordinator`.
  - Fail-safe + idempotent: an update is proposed only on a confident single match above threshold
    and only when it actually changes the derived status; otherwise the normal new-note flow runs.
  - Contract: `SPEC-PR-B.md`.
- **Detail edits + per-note history + "what moved" digest (PR-C):** a second event kind, **`edit`**
  (note → title/body/tags/due), so progress on the *content* of an idea is recorded — never a
  mutation. The current note is **derived** (stored note + replayed edits, with the content-addressed
  `id` held stable), and the Planner, graph, **and** the note `.md` files all read it, so the three
  projections agree. Status/edit events now carry a **timestamp** (the capture's `created`; still no
  hidden clock).
  - **Per-note history** (`history_of`, the "git log for an idea") renders as a `## History` section
    in each note; a **`## What moved`** digest of recent events leads `Plan.md`'s body.
  - **Note `.md` re-render from derived state** (`write_projections(..., originals=…)`): a PR-B "done"
    capture now also shows `status: done` in the note file, and an edit shows the new
    title/body/tags/due — finishing the PR-A/B deferred item. A title edit re-renders in place; a
    sweep removes the stale old-title file (never a foreign/hand-written one).
  - **Capture-driven edits:** an `EditDetector` port — deterministic `HeuristicEditDetector`
    (due + retitle) and an Ollama `LlmEditDetector` (heuristic fallback) — recognises edit-intent
    ("launch slipped to Q3", "rename X to Y"), matches the note on the **verbatim capture** text, and
    proposes the edit in the review dialog → on approve appends an `edit` event (no duplicate note).
    Precedence: status > edit > new note.
  - Hardening: unknown/corrupt `index.jsonl` record kinds are now logged-and-skipped on rehydrate
    instead of silently dropped; `NoteEvent.kind` is a typed `Literal`.
  - Contract: `SPEC-PR-C.md`.
- **Resource references (PR-D):** a capture's artifacts — external **links**, **images**, local
  **files**, and **placeholder** expectations ("make a resume website") — are extracted by the
  organizer (`HeuristicOrganizer` regexes + the `OllamaOrganizer`'s `resources` JSON, with a heuristic
  fallback and ref sanitization) and carried as a **creation-time field** on the note (never part of
  the content-addressed `id`). They **render natively in Obsidian**: a `## Resources` section
  (`[label](url)`, `![[image]]`/`![label](url)`, `[[file]]`, and a visible placeholder) plus a
  frontmatter `resources:` list. The index serializes them (old records load as empty). The
  `resource` *event* kind + `resources_of` + the `grandplan attach` flow are PR-E. Contract:
  `SPEC-PR-D.md`.
- **Artifact-attach flow (PR-E):** a `resource` **event** kind makes attachments first-class — a
  real artifact (file path or URL) is attached to the existing note it fulfils as an append-only
  event (`add_resource`), with the derived `resources_of(note_id)` = creation-time resources +
  attachments folded into `current_note`, so the note `.md` (and the "what moved" digest) show it.
  New **`grandplan attach <path|url> -o <vault>`** command: classifies the ref, semantic-matches the
  note it fulfils (`--describe` to guide it, `--embeddings` to match a ST-built vault), attaches, and
  re-renders. Lossless (the note is never mutated) and safe (the ref is only recorded, never fetched).
  Deferred to later: capture-driven attach in the review dialog; propagation to related notes.
  Contract: `SPEC-PR-E.md`.

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
