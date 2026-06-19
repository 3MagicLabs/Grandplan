# HANDOFF — grandplan

> Working state for picking up in a fresh session (keeps multi-file feature work out of an
> exhausted context window, per the engineering rules).

## Where things stand (main)

The MVP is complete, gated, and running on the user's native-Windows machine. Recent merged work:

- **#36** stability: `CaptureCoordinator` (serialized single-worker, bounded queue, progress events, off-UI-thread) — fixed the OOM/freeze.
- **#37** US-10 richer reconciler (builds_on/refines/supersedes/contradicts) + consistency-by-projection (ADR-0007).
- **#38** hardening: QAS-1 offline-egress test, vault-clobber guard, US-9 portability, Windows quickstart + `run.bat`.
- **#39** fix: `_ReviewRequest` hashable (GUI capture crash).
- **#40** clean note filenames (id → frontmatter/aliases, alias-based links), valid Obsidian tags, richer frontmatter.
- **#41** index moved OUT of the (OneDrive-)synced vault to `~/.grandplan/<vault>` (`GRANDPLAN_HOME` overridable) + one-time migration.
- **#42** wired `LlmRelationshipClassifier` into the GUI with two-tier linking (`llm_top_k`).
- **#43** docs: ADR-0008 (event-sourced "git for ideas" + resources) + this HANDOFF.
- **#44** PR-A — event-sourced **status** substrate (see the phased plan below): `status` events in
  `index.jsonl`, `set_status`/`status_of` on both repos, Planner derives status (`Plan.status_by_id`),
  vault/graph render derived status. Contract: `SPEC-PR-A.md`.
- **PR-B** (branch `feat/pr-b-capture-driven-status-updates`) — capture-driven status updates: a
  progress capture ("done: …", "started …", "up next …", "reopen …") is detected as an **update**,
  matched to the relevant note by embedding similarity, proposed in the review dialog, and on approve
  appends a `status` event (no duplicate note; original never mutated; raw capture kept in inbox).
  New `UpdateDetector` port + `HeuristicUpdateDetector` (word-boundary cues → DONE/ACTIVE/NEXT,
  reopen→ACTIVE) + Ollama `LlmUpdateDetector` (heuristic fallback); `start_review`/`approve` branch
  to a `StatusUpdate`/`StatusUpdateResult`; coordinator + GUI wired. Contract: `SPEC-PR-B.md`.
- **PR-C** (branch `feat/pr-c-edit-events-history-digest`, stacked on PR-B) — detail edits + per-note
  history + "what moved" digest: an `edit` event kind (note→title/body/tags/due) + timestamps (`at`)
  on status/edit events (from the capture's `created`, no hidden clock); derived **current note**
  (`current_note`/`current_notes`) read by planner/graph/vault so all three projections agree;
  `history_of` per-note git-log → a `## History` section in each note `.md`; a `## What moved` digest
  in `Plan.md`; **note `.md` re-render from derived state** (`write_projections(..., originals=...)`
  → `write_notes` with an orphan sweep for title-edit renames) — finishing the PR-A/B deferred item;
  capture-driven edits via `EditDetector` (`HeuristicEditDetector` due/retitle + Ollama
  `LlmEditDetector`), matched on the **verbatim capture** embedding, proposed in the review dialog,
  `approve` → `record_edit` (no new note). Precedence status > edit > new note. Contract:
  `SPEC-PR-C.md`. Also: log-and-skip on unknown `index.jsonl` record kinds (closes the deferred
  corrupt-record hardening); `NoteEvent.kind` is a `Literal`.

- **PR-D** (branch `feat/pr-d-resource-references`, stacked on PR-C) — resource references: a
  `Resource` (link/image/file/placeholder) extracted from the capture (organizer; LLM + heuristic),
  carried as a creation-time field on the note, rendered natively in the note `.md` (`## Resources` +
  frontmatter `resources:`). The `resource` event kind + attach flow are PR-E. Contract: `SPEC-PR-D.md`.
- **PR-E** (branch `feat/pr-e-attach-flow`, stacked on PR-D) — artifact-attach flow: a `resource`
  **event** kind + `add_resource`/`resources_of` (folded into `current_note`) + a `grandplan attach
  <path|url>` CLI that semantic-matches the note an artifact fulfils and attaches it (re-rendering the
  note `.md` with the resource + history; the attach shows in the "what moved" digest). `attach` only
  *records* the ref (no fetch). Deferred: capture-driven attach in the review dialog; propagation to
  related notes. Contract: `SPEC-PR-E.md`.

Gate: **506 tests, 98% coverage**, all green; CI mirrors it.

## Operational notes for the user's machine
- Run on **native Windows** (Python 3.12 from python.org, not Anaconda), `--llm --embeddings`, model `llama3.2:3b`.
- **Cap WSL** (`~/.wslconfig` `memory=4GB`) or it competes with the Windows app for 16 GB → freeze.
- `git pull` then relaunch (editable install; no reinstall needed).

## Next: PR-F → PR-G (output quality, then the relational keystone) — see **FINDINGS.md**

The "git for ideas" program (PR-A…PR-E) is **DONE**. A 2026-06-17 diagnosis (`FINDINGS.md`) found
the generated graph/plan still feels meaningless for two reasons the roadmap never addressed:
the LLM silently degrades to a keyword heuristic (so the live vault is all heuristic output), and
**no code path ever creates the structural edges** (`part_of`/`depends_on`/…) the planner needs.
Remediation is **PR-F** (trustworthy output) then **PR-G** (relational organization — the keystone),
ahead of voice capture (now PR-H). The ADR-0008 PR list below (PR-A…PR-E) is the completed history;
the new work is items 6–8. Each PR: TDD + gated + reviewed + CI-merged (the loop used for #36–#42):

1. **PR-A — event substrate** ✅ **DONE** (branch `feat/pr-a-event-substrate-status`): `status`
   record kind in `index.jsonl` (`note_store.py` `_apply`/`set_status`, idempotent — no event when
   status unchanged); `set_status` + `status_of(note_id)` on the `NoteRepository` port + both impls;
   `planner.build_plan` derives status via `repo.status_of` (now/blocked/done-unblocks/needs-review/
   tree checkbox), carried on `Plan.status_by_id`; `vault._frontmatter`/`render_markdown`/`write`
   take an optional derived `status`; `graph.json` node shows derived status too. SPEC-PR-A.md is the
   contract. Gate: **354 tests, 97% cov**, ruff/mypy/bandit green. Deferred (out of PR-A scope, see
   code review): (a) re-render a note's `.md` frontmatter on a status event — **PR-C** (`commit`
   writes creation status; pass `repo.status_of(note.id)` when re-rendering); (b) `_apply` crashes on
   a malformed/corrupt `status`/`note`/`edge` record (pre-existing for all kinds) — wrap with
   log-and-skip in a focused hardening PR; (c) `set_status` on an unknown `note_id` stores an orphan
   event — guard once PR-B's match-then-update path exists.
2. **PR-B — capture-driven status updates** ✅ **DONE** (branch
   `feat/pr-b-capture-driven-status-updates`): `core/update_detect.py` (`UpdateDetector` port +
   deterministic `HeuristicUpdateDetector`, word-boundary cue matching → DONE/ACTIVE/NEXT, reopen→
   ACTIVE); `adapters/llm_update_detector.py` (Ollama-backed, injected client, JSON-validated,
   heuristic fallback); `app/review.py` gains `StatusUpdate`/`StatusUpdateResult`, `start_review`
   runs detector+similarity match (`match_threshold` 0.5, idempotent + fail-safe), `approve` branches
   to `repo.set_status` (no `add_note`, no vault write); `app/coordinator.py` injects the detector and
   returns `CaptureResult | StatusUpdateResult`; `app/gui.py` wires the detector (LLM under `--llm`,
   else heuristic) and shows the update in the review dialog. SPEC-PR-B.md is the contract. Gate:
   **402 tests, 97% cov**, ruff/mypy/bandit green. Deferred to **PR-C** (per the SPEC + PR-A
   follow-ups): re-render the matched note's `.md` frontmatter on a status event (today the `.md`
   frontmatter is stale until re-created; Plan.md/graph.json already reflect the new status); a
   "create a new note instead" button when the match is wrong (today: discard + re-capture).
3. **PR-C — detail edits + history + digest** ✅ **DONE** (branch
   `feat/pr-c-edit-events-history-digest`, stacked on PR-B): `edit` event kind + `NoteEdit`/`NoteEvent`
   models + `apply_edit` (id stable); timestamps (`at`) on status/edit events from the capture's
   `created`; `record_edit`/`current_note`/`current_notes`/`history_of`/`events` on both repos;
   planner+graph+vault read derived current notes; `## What moved` in `Plan.md`, `## History` per note;
   `write_projections(..., originals=...)`→`write_notes` re-renders note `.md` from derived state +
   orphan sweep; `core/edit_detect.py` + `adapters/llm_edit_detector.py`; `review.approve` returns
   `CaptureResult | StatusUpdateResult | EditResult`; coordinator/gui/cli wired. SPEC-PR-C.md is the
   contract. Gate: **464 tests, 98% cov**. Deferred to **PR-D+**: clearing a field (due→None); a
   "create a new note instead" dialog button when a match is wrong.
4. **PR-D — resource references (schema + render)** ✅ **DONE** (branch `feat/pr-d-resource-references`,
   stacked on PR-C): `core/resources.py` (`Resource`/`ResourceKind` link/image/file/placeholder +
   `extract_resources`); creation-time `resources` field on `ProposedNote`/`Note` (not in the `id`);
   Heuristic + Ollama organizers extract (LLM `resources` JSON + heuristic fallback; refs sanitized);
   note_store serializes (old records → `()`); vault renders a `## Resources` section + frontmatter
   `resources:`. SPEC-PR-D.md. Gate: **489 tests, 98% cov**. Deferred to PR-E: the `resource` **event**
   kind + `resources_of` + the `grandplan attach` capture-driven attach-to-existing-note flow.
5. **PR-E — artifact-attach flow** ✅ **DONE** (branch `feat/pr-e-attach-flow`, stacked on PR-D):
   `resource` event kind (`NoteEvent.kind` += "resource") + `add_resource`/`resources_of` on both
   repos (derived into `current_note`); `core/resources.py` `classify_reference`/`describe_reference`;
   `core/attach.py` `attach()` (single best semantic match, threshold 0.30, only records the ref);
   `grandplan attach <ref> -o <vault> [--describe] [--embeddings]` CLI (persistent index + re-project).
   SPEC-PR-E.md. Gate: **506 tests, 98% cov**. Deferred: capture-driven attach in the review dialog;
   propagation to related notes; auto status bump.
6. **PR-F — trustworthy organization** ✅ **DONE** (RC1+RC4 in `FINDINGS.md`). The live vault is
   100% *heuristic* output (truncated-text titles, noise tags, verbatim bodies) and partly from an
   old build (no `type/…` color tags) — the LLM is opt-in (`cli.py:61,114`) and degrades *silently*
   when Ollama is down (`ollama_organizer.py:169`). Scope: (a) make the LLM the **default** and
   **fail loudly** when the model is unavailable — surface it in CLI/GUI, keep the raw capture in
   inbox for "organize later", never write heuristic garbage as if it were the model; (b) a
   `grandplan regenerate` command that re-organizes + re-renders the **whole** vault from stored
   originals so structural tags + graph color + clean titles/tags/bodies appear (closes the "stale
   vault" gap); (c) an **organize-quality QAS** so output quality is measured, not assumed.
   **Delivered** (2 commits, branch `feat/pr-f-trustworthy-organization`): `OrganizerUnavailable` +
   `require=True` (fail-loud); LLM default in CLI/GUI (`--no-llm` opts out, `--llm` kept as no-op);
   `core/quality.py` (QAS-8 fingerprints); `core/report.py` diagnostic report printed on every
   `organize`/`regenerate` (structural-vs-semantic edges, low-quality notes, "model likely never ran");
   `grandplan regenerate` (atomic rebuild from inbox originals, backs up old index, fail-safe);
   `grandplan doctor` (read-only health report). `SPEC-PR-F.md`. Gate at commit: 523 tests, 97% cov.
7. **PR-G — relational organization (THE KEYSTONE)** ✅ **DONE** (RC2+RC3 in `FINDINGS.md`). Audit fact: the
   **only** edges ever created come from embedding similarity (`pipeline.py:97`); nothing produces
   `part_of`/`depends_on`/`blocks`/`next`, yet the planner consumes exactly those
   (`planner.py:277-331`) — so the masterplan is flat, the plan never sequences, and connections are
   just "similar text". Scope: a new **placement** stage (port + `HeuristicPlacer` +
   `LlmPlacer` adapter) that, for a new note, proposes structural edges against the existing graph
   (parent `part_of`, prerequisites `depends_on`/`blocks`) **human-approved, append-only — never
   mutating a stored note** (edges + events only, per ADR-0007/0008), and lifts `horizon`
   accordingly. This materializes the hierarchy, the dependency DAG, and the sequenced Now/Blocked
   plan (US-8 / SPEC §11.1). **Delivered** (branch `feat/pr-f-trustworthy-organization`, stacked):
   `core/placement.py` (`Placer` port, `Placement`, `HeuristicPlacer` part_of by horizon-rank+similarity,
   `record_placement` guarded edges); `adapters/llm_placer.py` (`LlmPlacer` parent+depends_on, id-validated,
   heuristic fallback); wired into CLI `organize`/`regenerate` and the GUI flow
   (`review.start_review`/`approve` → coordinator → gui). Placement runs before commit; edges recorded
   on approve; append-only. `SPEC-PR-G.md`. Gate: 535 tests, 98% cov. Verified end-to-end via CLI: a
   goal/project/task input nests the task under the project in Plan.md with a real `part_of` edge.
   **Deferred** (didn't block): `blocks`/`next`/`waiting_on` inference (only part_of+depends_on now);
   human review/edit of a proposed placement in the GUI dialog (auto-applied + shown in the report);
   RC5 slug-based linking (separate, lower priority).
8. **PR-H** voice capture (offline STT) behind the `Capturer` port. *(was PR-F)*

### How to test now (the comprehensive output the user asked for)
- **Default path needs Ollama running** with the model pulled (`ollama serve` + `ollama pull
  llama3.2:3b`). `grandplan organize <file> -o <vault>` / the GUI now use the LLM by default and
  **fail loud** with guidance if the model is unreachable (capture preserved in inbox).
- Every `organize`/`regenerate` prints a **report**: notes/types/horizons, structural-vs-semantic
  edges, low-quality notes (QAS-8), isolated notes. `grandplan doctor -o <vault>` prints it read-only.
- To upgrade an old heuristic-era vault: `grandplan regenerate -o <vault>` (re-organizes from the
  lossless inbox originals; backs up the old index to `index.jsonl.bak`).
- With `--no-llm` everything is honest but flat/low-quality (heuristic) — the report says so.

### Invariants to honor (don't regress)
- **Lossless/append-only**: never mutate a stored note/original; updates are *events*, current state is *derived* (ADR-0007/0008).
- Keep the gate green (`ruff format --check`, `ruff check`, `mypy src`, `bandit -r src`, `pytest --cov`); branch off `main` (don't commit to main); one PR per slice; independent code review before merge.
- Optional deps stay lazily imported; tests hermetic (CI has no `[gui,llm,embeddings]` extras).
