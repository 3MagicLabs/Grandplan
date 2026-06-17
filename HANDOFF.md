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

Gate: **464 tests, 98% coverage**, all green; CI mirrors it.

## Operational notes for the user's machine
- Run on **native Windows** (Python 3.12 from python.org, not Anaconda), `--llm --embeddings`, model `llama3.2:3b`.
- **Cap WSL** (`~/.wslconfig` `memory=4GB`) or it competes with the Windows app for 16 GB → freeze.
- `git pull` then relaunch (editable install; no reinstall needed).

## Next: build the "git for ideas" program — see **ADR-0008** (event-sourced progress + resources)

User approved building the **whole** program (status updates + detail edits + history + resource
embedding + artifact-attach flow). Execute the PRs in ADR-0008 order, each TDD + gated + reviewed +
CI-merged (the loop used for #36–#42):

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
4. **PR-D** resource references (frontmatter `resources:`/`links:`, render Obsidian links/embeds/placeholders; organizer extracts URLs/paths).
5. **PR-E** `grandplan attach <path|url>` + capture-driven artifact attach (parse vault → match → attach → mark progress → propagate to related notes).
6. **PR-F** voice capture (offline STT) behind the `Capturer` port.

### Invariants to honor (don't regress)
- **Lossless/append-only**: never mutate a stored note/original; updates are *events*, current state is *derived* (ADR-0007/0008).
- Keep the gate green (`ruff format --check`, `ruff check`, `mypy src`, `bandit -r src`, `pytest --cov`); branch off `main` (don't commit to main); one PR per slice; independent code review before merge.
- Optional deps stay lazily imported; tests hermetic (CI has no `[gui,llm,embeddings]` extras).
