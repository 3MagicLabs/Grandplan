# SPEC — PR-C: detail edits + per-note history + "what moved" digest

> Implements PR-C of ADR-0008 ("git for ideas"). Builds on PR-A (`status` events) and PR-B
> (capture-driven status updates). Adds the second event kind — **`edit`** — plus per-note history
> and a progress digest, and finishes the PR-A/B deferred item: **re-render each note's `.md` from
> derived state**.

## Goal

1. **Edit events.** A field change (title / body / tags / due) is an appended **`edit`** event, never
   a mutation of the stored note. The *current* note is **derived** = stored note + replayed edits.
2. **Timestamps.** `status` and `edit` events carry a caller-supplied timestamp (`at`), so history is
   ordered in time. No hidden clock — the capture flow threads the capture's own `created`.
3. **Consistent projections.** The Planner, graph, and the note `.md` files all read the **derived
   current note** (edited fields + derived status), so the three views never disagree (the invariant
   PR-A established for status, now extended to fields).
4. **Per-note history** — `history_of(note_id)` is the note's "git log"; surfaced as a `## History`
   section in the note's `.md`.
5. **"What moved" digest** — a `## What moved` section in `Plan.md` listing the most recent events
   across the vault.
6. **Note `.md` re-render** (deferred PR-A/B item) — projections rewrite each note's file from its
   derived state, so a PR-B "done" capture now also shows `status: done` in the note file, and an
   edit shows the new title/body/tags/due.
7. **Capture-driven edits.** A capture expressing an edit ("launch slipped to Q3", "rename X to Y")
   is matched to the relevant note and **proposed as an edit in the review dialog** → on approve,
   append an `edit` event. Mirrors PR-B's status flow.

## Invariants (must not regress)

- **Lossless / append-only:** the stored `note` and `original` records are never mutated; an edit is
  a new `edit` event line; the note's content-addressed **`id` never changes** on edit (identity is
  stable; only derived fields change). The raw capture still lands in the inbox.
- **Human-in-the-loop:** edits (like status updates) are only *proposals* until approved.
- **No hidden clock:** events take a caller-supplied `at` (the capture's `created`); core never calls
  `datetime.now()`. `at` is optional — absent on direct API calls / pre-PR-C events.
- **Idempotency:** an edit that does not change the derived note appends nothing (parity with
  `set_status`). An edit to an unknown note id is a no-op (orphan guard).
- **Hermetic tests / lazy optional deps:** core uses no extras; the LLM edit detector lazily imports
  `ollama` and is unit-tested with an injected fake client.

## Contracts

### Models (`core/models.py`)
```python
@dataclass(frozen=True)
class NoteEdit:                       # a change to a subset of editable fields; None = leave unchanged
    title: str | None = None
    body: str | None = None
    tags: tuple[str, ...] | None = None
    due: str | None = None
    def is_empty(self) -> bool: ...   # no field set
def apply_edit(note: Note, edit: NoteEdit) -> Note   # returns a new Note (same id) with the edit applied
```
- `due` clearing (set to None) is out of scope: `None` means "unchanged" for every field.

### History event (`core/history.py` or `core/models.py`)
```python
@dataclass(frozen=True)
class NoteEvent:                      # one entry in a note's git-log
    note_id: str
    kind: str                        # "status" | "edit"
    at: str | None
    status: NoteStatus | None = None
    edit: NoteEdit | None = None
    def summary(self) -> str: ...     # "status → done" | "edit: due → Q3; title → …"
```

### `NoteRepository` port (`core/ports.py`) — new methods
```python
def record_edit(self, note_id: str, edit: NoteEdit, *, at: str | None = None) -> None: ...
def current_note(self, note_id: str) -> Note | None: ...   # stored note + replayed edits + derived status
def current_notes(self) -> tuple[Note, ...]: ...           # current_note for every stored note
def history_of(self, note_id: str) -> tuple[NoteEvent, ...]: ...   # this note's events, in order
def events(self) -> tuple[NoteEvent, ...]: ...             # all events, global append order
```
- `set_status` gains `*, at: str | None = None` (back-compatible; PR-A/B callers pass nothing).
- `record_edit`: no-op if the note is unknown, the edit `is_empty()`, or applying it changes nothing
  (idempotent). Otherwise records the event.
- `current_note`: `None` if the note is unknown; else the stored note with all its edits applied (in
  order) and `status` set to the derived status (`status_of`).

### Repositories
- **`InMemoryNoteRepository`**: a global `_events: list[NoteEvent]` (append order) drives status
  derivation (last `status` event), field derivation (`apply_edit` folded over the note's `edit`
  events), `history_of` (filter by id), and `events()`.
- **`JsonlNoteRepository`**: `_apply` handles `kind == "edit"` (replay) and reads `at` on `status`;
  `record_edit` appends `{"kind":"edit","note_id":…,"edit":{…},"at":…?}`; `set_status` appends `at?`.
  Round-trips and rehydrates (last-write-wins for status; edits replayed in order).

### Planner (`core/planner.py`)
- Iterate **`repo.current_notes()`** (derived fields + status) instead of `repo.notes()`.
- `render_plan` gains a **`## What moved`** section (most-recent-first, capped) built from
  `repo.events()` + the current note titles. `Plan` carries the digest lines so render stays pure.

### Graph (`core/graph.py`)
- Build nodes from `repo.current_notes()` (derived title/tags/status), so `graph.json` agrees.

### Note re-render (`core/project.py`)
- `write_projections(repo, vault_dir, *, originals=None)` also **re-renders each note's `.md`** from
  its derived state when `originals` is provided (the verbatim source is needed to keep the note
  lossless on disk). For each `current_note`: gather its outgoing edges + current target notes, fetch
  its `Original`, and `vault.write(..., status=derived)`. A title edit changes the slug → after
  writing, an **orphan sweep** removes any prior `.md` whose frontmatter `id` matches a re-rendered
  note but sits at a different path (never touches foreign files). `originals=None` ⇒ today's
  behaviour (graph + Plan only), so existing callers are unaffected.
- The note `.md` gains a **`## History`** section from `history_of` (rendered by `vault`).

### Capture-driven edits (`core/edit_detect.py`, `adapters/llm_edit_detector.py`, `app/review.py`)
- `EditDetector` port (Strategy): `detect(self, text: str) -> NoteEdit | None`.
  - `HeuristicEditDetector` (deterministic, offline): recognises **due** changes — an explicit
    "due"/"deadline" or a deadline-specific "slipped/pushed/bumped/rescheduled to <X>" (the vaguer
    "moved to" is excluded as too often non-date English; a leading "at/on/by" preposition is
    stripped) — and **retitle** ("rename … to <X>", "retitle to <X>", "call it <X>", keeping a title
    that itself contains "to"); else `None`. Body/tag edits are left to the LLM detector (too
    ambiguous to extract deterministically).
  - `LlmEditDetector` (`adapters`): Ollama-backed, asks for `{"edit": {title?,body?,tags?,due?}}` or
    `{"edit": null}`; validates → `NoteEdit`; deterministic fallback on any failure.
- `review.py`: `ProposedEdit(target, edit, score)` + `EditResult(original, target, edit)`.
  `PendingReview` gains `edit: ProposedEdit | None`. `start_review` runs detectors with precedence
  **status > edit > new note**; both match against the embedding of the **verbatim capture text**
  (not the organizer's reorganized proposal), so a retitle still locates its note even when an LLM
  organizer rewrites the title. `approve` branches:
  status → `set_status`; edit → `record_edit` (no new note, no add_note); else → new note. Each event
  is stamped with `pending.original.created` (the no-hidden-clock timestamp source).
- `ReviewState` gains `is_edit / edit_target_title / edit_summary` for the dialog.

### Coordinator + GUI
- `CaptureCoordinator` gains an injected `edit_detector`; result union widens to include `EditResult`;
  `SAVED`/`COMMITTING` detail is human-readable for all three outcomes; `after_commit` (re-projection,
  now with `originals`) runs for all.
- `gui.run_app` wires `LlmEditDetector` under `--llm` else `HeuristicEditDetector`, passes `originals`
  into re-projection, and shows the proposed edit in the dialog.
- `cli.py`: pass `originals` into `write_projections` so the CLI re-renders notes too.

## Tests (write first — RED), by layer

1. **models:** `apply_edit` applies each field, leaves unset fields, keeps the **id stable**;
   `NoteEdit.is_empty`; `NoteEvent.summary`.
2. **repository / note_store:** record an edit → `current_note` reflects it; multiple edits compose
   in order (last wins per field); edit persists & rehydrates; idempotent (no-op edit / unknown note
   → no event); `status` events carry `at` and rehydrate; `history_of` returns ordered events;
   `events()` is global order.
3. **planner / graph:** an edited title shows in `Plan.md`/`graph.json`/tree; a `## What moved`
   section lists recent status + edit events, most-recent-first, capped.
4. **project (note re-render):** `write_projections(..., originals=...)` rewrites a note's `.md` to
   the derived status + edited fields, adds a `## History` section, and a **title edit doesn't leave
   an orphan file**; `originals=None` keeps today's behaviour; foreign files untouched.
5. **edit_detect / llm_edit_detector:** due + retitle cues → the right `NoteEdit`; no cue → `None`;
   LLM parse/validate/fallback (null ⇒ None, bad ⇒ heuristic fallback).
6. **review / coordinator / e2e:** a capture-driven edit matches a note, proposes the edit, and on
   approve appends an `edit` event (no new note) that survives a reopen and shows in the re-rendered
   `.md` + the `Plan.md` digest; status precedence over edit; `detector=None`/`edit_detector=None`
   keep prior behaviour.

## Out of scope (later PRs)

Clearing a field (due → None); resource references & rendering (PR-D); `grandplan attach` (PR-E);
voice (PR-F). Conflict handling when two edits race is last-write-wins per field (append order).
