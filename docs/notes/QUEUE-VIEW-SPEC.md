# Live capture-queue view ("carousel") — SPEC

A tray window that shows **every capture in the line** and watches each one get made in
real time: the in-flight note advancing stage-by-stage, the notes queued behind it with their
place in line, and the ones just saved. Vertical-pipeline layout (chosen 2026-07-10).

```
┌─ grandplan · capture queue ────────────────────┐
│ ● NOW  🖥️ "Q3 planning notes…"                  │
│   capture ▸ ANALYZING ▸ review ▸ commit ▸ save  │
│           ▓▓▓▓▓▓░░░░  organizing with local AI  │
│ ─────────────────────────────────────────────── │
│ ②  📱 "link to that article…"     queued        │
│ ③  🖥️ "reply to recruiter…"       queued        │
│ ─────────────────────────────────────────────── │
│ ✓  "meeting recap"        saved · 2s ago        │
└─────────────────────────────────────────────────┘
```

## Contract

### Coordinator (Qt-free, unit-tested) — `app/coordinator.py`
- `queue_snapshot() -> tuple[QueueItem, ...]`: an ordered, immutable snapshot —
  **in-flight first** (position 0, live `stage`), then **queued** (positions 1..N), then the
  **most-recent finished** (cap 5, most-recent first). Thread-safe (guarded by one lock).
- `QueueItem(id, snippet, source, state, stage, position, detail)` — frozen. `state ∈ ItemState`
  (`QUEUED | IN_FLIGHT | SAVED | DISCARDED | FAILED | EMPTY`); `stage` is the live `Stage` only
  while `IN_FLIGHT`, else `None`.
- Each capture is mirrored by a descriptor that tracks the `queue.Queue` in FIFO lockstep (the
  `Queue` can't be peeked). Descriptor is created at **enqueue** (so it carries the text snippet
  + source the moment you fire the capture), promoted to in-flight when the worker pulls it,
  advanced by the pipeline stages, then moved to the recent-history ring on `IDLE`.
- New `Stage.QUEUED`, emitted on a successful enqueue, so the view refreshes the instant a note
  joins the line (not only on the next stage change of the in-flight note).
- Only the pipeline transitions inside `_process` mutate the in-flight descriptor (`_advance`);
  submit-path emits (`EMPTY`/`REJECTED_BUSY`/`QUEUED`) and `ENRICHED` never touch it.

### Pure view model — `app/progress.py`
- `PIPELINE_STAGES` — the ordered strip (capture ▸ analyze ▸ review ▸ commit ▸ save).
- `row_for(item: QueueItem) -> QueueRowView` — icon (📱 phone / 🖥️ desktop), snippet, one status
  line ("#N in line" / a stage headline / "saved ✓"), bar percent, section (`now`/`queued`/`done`),
  and — for the in-flight row — the per-step states (`done`/`active`/`todo`). Fully unit-tested.

### Qt widget (thin renderer, `pragma: no cover`) — `app/queue_view.py`
- `QueueView(QWidget)` with `update(items)` — rebuilds the three sections from `row_for`.
  Opened/raised from a tray menu item; refreshed on every `status_changed`.

## Edge cases
- Empty line → the window shows "nothing in the queue" placeholder, stays open.
- REJECTED_BUSY (buffer full) → no descriptor is created (put_nowait failed first).
- Blank-text capture that reaches the worker → EMPTY → dropped from history (no phantom row).
- Snapshot is a copy; the widget never holds live descriptors (no cross-thread mutation).

## Non-goals (follow-ups)
- Per-app desktop icons (Notepad vs Gmail) need the capturer to tag the foreground window —
  out of scope here to avoid touching the safety-critical capture path.
- No click-to-cancel a queued item (view is read-only for now).
