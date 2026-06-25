# SPEC — PR-B: capture-driven status updates

> Implements PR-B of ADR-0008 ("git for ideas"). Builds on the PR-A `status` event substrate
> (`SPEC-PR-A.md`): a capture that expresses *progress on an existing idea* updates the matched
> note's **status** (an event) instead of creating a duplicate note.

## Goal

Turn a free-text capture like "done: built the resume" or "started the landing page" into a
**proposed status change on the relevant existing note**, surfaced in the same human-in-the-loop
review dialog. On approval, append a `status` event (PR-A) and re-project — never mutating the note,
never creating a second note. This is the "commit a change" verb of ADR-0008, reusing the existing
capture → embed → match → review → re-project machinery.

The flow: **capture → organize/embed → detect update-intent → match the relevant note (similarity)
→ propose the status change → human approves → append `status` → re-project.**

## Invariants (must not regress)

- **Lossless / append-only (QAS-2, ADR-0007/0008):** the raw capture is still written verbatim to
  the inbox (`OriginalStore`); the matched note is **never mutated**; the update is a new `status`
  event line (PR-A). An approved update creates **no new `note` record**.
- **Human-in-the-loop (US-4):** nothing is auto-applied. The update is only a *proposal* until the
  user approves it in the review dialog. Discarding writes nothing (the raw capture stays in the inbox).
- **Idempotency:** if the matched note's *derived* status already equals the detected target, **no
  update is proposed** (mirrors `set_status`'s no-op-on-equal; PR-A).
- **Fail-safe matching:** an update is proposed only when a single best match clears `match_threshold`.
  Update-intent with no confident match falls back to the normal **new-note** flow (no wrong note is
  ever touched).
- **Hermetic tests / lazy optional deps:** the core detector + matching use no `[gui,llm,embeddings]`
  extras. The LLM detector lazily imports `ollama` and is exercised with an injected fake client (CI
  has no `[llm]` extra), exactly like `OllamaOrganizer` / `LlmRelationshipClassifier`.

## Update vocabulary (maps only to existing `NoteStatus`)

| Intent     | Target `NoteStatus` | Example cues                                                    |
|------------|---------------------|-----------------------------------------------------------------|
| `done`     | `DONE`              | done, finished, completed, shipped, wrapped up, ✅, `[x]`         |
| `active`   | `ACTIVE`            | started, working on, in progress, underway, began, kicked off   |
| `next`     | `NEXT`              | up next, next up, do next, queued, queue, on deck               |
| `reopen`   | `ACTIVE`            | reopen, re-open, not done, not finished, no longer done         |

`reopen` is checked **before** `done` so "not done" is never misread as completion. No new statuses
are introduced; `NEEDS_REVIEW`/`SUPERSEDED` are **not** reachable via this path (they are derived
from contradiction/supersede edges — setting them directly would be a footgun).

## Contracts

### `UpdateDetector` port (`core/update_detect.py`) — Strategy (ADR-0003/0007)
```python
class UpdateDetector(Protocol):
    def detect(self, text: str) -> NoteStatus | None: ...
```
- Returns the target `NoteStatus` if the text expresses update-intent, else `None`.
- `UPDATE_STATUS: dict[str, NoteStatus]` is the canonical intent→status map (shared with the LLM parser).

### `HeuristicUpdateDetector` (`core/update_detect.py`) — deterministic, offline baseline
- Ordered cue rules (first match wins; `reopen` before `done`); lowercased substring match.
- No LLM, no clock, no IO. The default detector and the LLM detector's fallback.

### `LlmUpdateDetector` (`adapters/llm_update_detector.py`) — Ollama-backed, with deterministic fallback
- `__init__(self, *, model=DEFAULT_MODEL, chat=_ollama_chat, fallback: UpdateDetector | None = None)`.
- Asks the local model for `{"update": <done|active|next|reopen|none>}`; `parse_update(raw)` returns
  the mapped `NoteStatus` (or `None` for `"none"`). On any model/parse/transport failure → logs a
  warning and delegates to the deterministic fallback (`HeuristicUpdateDetector`). Lazy `import ollama`.

### Review view-model (`app/review.py`)
```python
@dataclass(frozen=True)
class StatusUpdate:           # a proposed status change on an existing note
    target: Note
    status: NoteStatus
    score: float

@dataclass(frozen=True)
class StatusUpdateResult:     # the outcome of an approved status update (no new note)
    original: Original
    target: Note
    status: NoteStatus
```
- `PendingReview` gains `update: StatusUpdate | None = None`.
- `ReviewState` gains `is_status_update: bool = False`, `update_target_title: str = ""`,
  `update_status: str = ""` so the dialog can render "Mark '<target>' as <status>".
- `start_review(...)` gains `detector: UpdateDetector | None = None` and
  `match_threshold: float = _DEFAULT_MATCH_THRESHOLD`. After `assess`, it runs the detector on the
  **verbatim original text**; if an intent is detected, it matches via
  `repo.most_similar(assessment.embedding, limit=1, threshold=match_threshold)`. The top match
  becomes the `StatusUpdate` target — **unless** the match's derived status already equals the
  detected status (idempotent → no proposal). `detector is None` ⇒ no update detection (unchanged flow).
- `approve(...)` returns `CaptureResult | StatusUpdateResult`. When `pending.update` is set it calls
  `repo.set_status(target.id, status)` and returns a `StatusUpdateResult` (no `add_note`, no vault
  write). Otherwise the existing new-note path is unchanged.
- `discard(...)` is unchanged (writes nothing; raw capture retained).

### Coordinator (`app/coordinator.py`)
- `__init__` gains `detector: UpdateDetector | None = None`, passed through to `start_review`.
- `process_one` / `_process` return `CaptureResult | StatusUpdateResult | None`.
- `SAVED` detail is human-readable for both outcomes (`"<title> → <status>"` for an update,
  the file path for a new note). `after_commit` (re-projection) runs for both; its type widens to
  `Callable[[CaptureResult | StatusUpdateResult], None]` (the hook already ignores its argument).
- No new stage is needed: an update reuses `AWAITING_REVIEW → COMMITTING → SAVED → IDLE`.

### GUI wiring (`app/gui.py`)
- Build `LlmUpdateDetector(model=model)` under `--llm`, else `HeuristicUpdateDetector()`, and pass it
  to the coordinator. The review dialog shows the update proposal when `state.is_status_update`.

## Re-projection (already wired by PR-A — no new planner code)

After an approved update, `write_projections` re-derives `Plan.md`/`graph.json` from the event log:
`status_of` now returns the new status, so e.g. a `DONE` event leaves "Now" and **unblocks
dependents**, a `NEXT`/`ACTIVE` keeps a task actionable, and `reopen → ACTIVE` brings a finished task
back into the plan. (PR-A's planner already reads derived status; PR-B only feeds it events.)

## Tests (write first — RED)

- **update_detect:** each cue family → the right `NoteStatus`; `reopen` cues win over `done`
  ("not done" ⇒ `ACTIVE`, not `DONE`); no cue ⇒ `None`; empty/whitespace ⇒ `None`; case-insensitive.
- **llm_update_detector:** prompt mentions the vocabulary + JSON; `parse_update` maps each key and
  `"none"` ⇒ `None`; unknown key raises; non-object raises; valid client response is used; client
  failure / bad JSON falls back to the heuristic.
- **review:** an update capture matching an existing note yields `pending.update` (correct target +
  status) and `state.is_status_update`; `approve` appends a `status` event (`repo.status_of` reflects
  it), writes **no** new note, returns `StatusUpdateResult`; the raw original is retained in the inbox;
  update-intent with **no** confident match falls back to a normal new-note review/commit; an update
  to a note already in the target status proposes nothing (idempotent).
- **coordinator:** a capture-driven update emits the full stage sequence ending in `SAVED`/`IDLE`,
  applies the status (no new note added), and runs `after_commit` once; with `detector=None` behaviour
  is unchanged.
- **e2e:** seed a task, then a second-session capture "done ..." matches it and (on approve) flips its
  derived status to `DONE`, removing it from `Plan.md`'s "Now" — proving the event-sourced update
  survives a repository reopen and re-projects, with **no** second note created.

## Out of scope (later PRs)

Re-rendering the matched note's own `.md` frontmatter on a status event (PR-C, a deferred PR-A
follow-up); `edit` events + per-note history + "what moved" digest (PR-C); resource references &
rendering (PR-D); `grandplan attach` (PR-E); voice capture (PR-F). A "create a new note instead"
button in the dialog when the match is wrong is a GUI nicety deferred past PR-B (today: discard and
re-capture).
