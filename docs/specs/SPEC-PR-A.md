# SPEC — PR-A: event substrate (status events)

> Implements PR-A of ADR-0008 ("git for ideas"). Foundation for capture-driven progress (PR-B+).
> Scope confirmed: planner **+** vault **+** graph all read derived status, so the three
> projections never disagree.

## Goal

Make `index.jsonl` a true event log for **status**: append a `status` event (note → new status)
instead of mutating the note. Current status is **derived** by replaying the log (last event wins).
The Planner, vault frontmatter, and `graph.json` all read the *derived* status, not the note's
creation-time status.

## Invariants (must not regress)

- **Lossless / append-only (QAS-2, ADR-0007/0008):** a stored `note` record is never mutated or
  rewritten. A status change is a *new* `status` event line. Originals are untouched.
- **No hidden clock / determinism:** no `datetime.now()`. (Status events carry no timestamp in
  PR-A; per-note history with timestamps is PR-C.)
- **Hermetic tests / lazy optional deps:** core changes use no `[gui,llm,embeddings]` extras.
- **Idempotency parity:** like `add_note`/`add_edge`, recording a status equal to the current
  derived status appends **nothing** (no redundant event, no state change).

## Contracts

### `NoteRepository` port (`core/ports.py`)
```python
def set_status(self, note_id: str, status: NoteStatus) -> None: ...
def status_of(self, note_id: str) -> NoteStatus | None: ...
```
- `status_of` returns the **effective** current status: the latest `status` event if one exists,
  else the note's creation status, else `None` if the note is unknown.
- `set_status` records a new current status (event-sourced; last-write-wins).

### `InMemoryNoteRepository` (`core/repository.py`)
- New `_statuses: dict[str, NoteStatus]` (note_id → latest recorded status).
- `set_status`: `self._statuses[note_id] = status` (unconditional last-write-wins).
- `status_of`: `_statuses[id]` if present; else `_notes[id].status`; else `None`.

### `JsonlNoteRepository` (`core/note_store.py`)
- `_apply`: `kind == "status"` → `self._mem.set_status(note_id, NoteStatus(status))`.
- `set_status`: if `self._mem.status_of(note_id) is status` → return (idempotent, no event).
  Else update `_mem` and `_append({"kind":"status","note_id":id,"status":status.value})`.
- `status_of`: delegate to `_mem`.
- Record shape: `{"kind": "status", "note_id": "<id>", "status": "<value>"}`.

### Planner (`core/planner.py`)
- Compute `status_by_id = {nid: repo.status_of(nid) for nid in notes}` once.
- `done`, `_actionable`, needs-review flag, and the `_render_tree` checkbox all read
  `status_by_id` instead of `note.status`. `done` → leaves "Now" and unblocks dependents.
- `Plan` gains `status_by_id: dict[str, NoteStatus]` so `render_plan` stays consistent.

### Vault (`core/vault.py`) + `VaultWriter` port
- `write(...)`, `render_markdown(...)`, `_frontmatter(...)` gain keyword `status: NoteStatus | None = None`.
- `None` → use `note.status` (backward-compatible; current callers unchanged).
- Frontmatter `status:` renders `(status or note.status).value`.

### Graph (`core/graph.py`)
- `to_graph` passes `repo.status_of(note.id)` into the node so `graph.json` shows derived status.

## Tests (write first — RED)

- **repository:** no event → `status_of` = creation status; after `set_status(DONE)` → `DONE`;
  unknown id → `None`.
- **note_store:** status event persists & rehydrates (last-write-wins across reopen); re-recording
  the same status appends no new line (idempotent); status for a note set before reopen survives.
- **planner:** `set_status(task, DONE)` removes it from `now` and unblocks its dependents;
  `set_status(task, NEEDS_REVIEW)` flags it into "Needs review" and out of `now`; tree checkbox
  reflects derived `DONE`.
- **vault:** `render_markdown(..., status=DONE)` emits `status: "done"` in frontmatter while the
  note's own `.status` differs (proves derivation, not mutation).
- **graph:** node `status` reflects `set_status` (derived), not the creation status.

## Out of scope (later PRs)

`edit`/`resource`/`link` events, per-note history & "what moved" digest (PR-C), capture-driven
update detection (PR-B), resource rendering (PR-D), `attach` (PR-E), voice (PR-F).
