"""CaptureCoordinator — serialize captures, surface progress, isolate failures (ADR-0006).

The tray GUI used to run the whole capture pipeline (local LLM + embeddings + the modal review
dialog) synchronously on the Qt main thread, inside `pragma: no cover` closures. A modal dialog
spins a nested event loop, so the trigger timer could *re-enter* and stack multiple concurrent
pipelines — exhausting memory — while also silently coalescing back-to-back captures into one.

This class extracts that orchestration into a **Qt-free, fully unit-tested** unit:

- **Serialized & bounded** — one worker thread drains a queue capped at `max_pending` (default 16):
  you can fire several captures in a row (each grabs its own text at submit time) and they're
  reviewed/committed one after another; only when the buffer fills is a `submit()` *rejected with a
  visible status*, never stacked or silently dropped. Serialization means only one local-LLM call
  runs at a time (so the model runtime can't fan out into parallel copies).
- **Observable** — every stage is logged and emitted as a `CaptureStatus` to an injected `on_status`
  callback (the GUI maps it to the tray tooltip/notifications).
- **Off the UI thread** — all heavy work runs on the worker; the only main-thread step is the
  injected `review(state) -> bool` decision (the GUI marshals it; tests pass a plain function).
- **Fault-isolated** — one capture's failure is reported as `FAILED`; the worker keeps serving.

It reuses the tested `app.review` controller — it adds *coordination*, not pipeline logic.
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from grandplan.app.review import (
    EditResult,
    PendingReview,
    ReviewState,
    StatusUpdateResult,
    approve,
    discard,
    start_review,
)
from grandplan.core.edit_detect import EditDetector
from grandplan.core.models import Source
from grandplan.core.pipeline import CaptureResult
from grandplan.core.placement import Placer
from grandplan.core.ports import Capturer, Embedder, NoteRepository, Organizer, VaultWriter
from grandplan.core.reconcile import Reconciler
from grandplan.core.store import OriginalStore
from grandplan.core.update_detect import UpdateDetector

# Any capture outcome: a new note, a status update (PR-B), or a field edit (PR-C) — all ADR-0008.
Committed = CaptureResult | StatusUpdateResult | EditResult

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 0.2  # seconds the worker waits on the queue before re-checking the stop flag
_JOIN_TIMEOUT = 5.0  # seconds stop() waits for the worker to finish its current capture
_ENRICH_BACKLOG_CAP = (
    256  # queued-enrichment bound; beyond it, notes just keep baseline links (#38)
)


class Stage(str, Enum):
    """A point in one capture's lifecycle, emitted for visibility (US-7)."""

    QUEUED = "queued"  # accepted into the line, waiting behind the in-flight capture (queue view)
    CAPTURING = "capturing"
    ANALYZING = "analyzing"  # organize (local LLM) + embed + reconcile
    AWAITING_REVIEW = "awaiting_review"
    COMMITTING = "committing"
    SAVED = "saved"
    DISCARDED = "discarded"
    EMPTY = "empty"  # nothing was selected
    FAILED = "failed"  # the capture itself failed; nothing was committed
    PROJECTION_FAILED = "projection_failed"  # the note WAS saved, but refreshing the plan failed
    REJECTED_BUSY = "rejected_busy"  # a submit was refused because a capture is already in progress
    IDLE = "idle"  # back to ready; always the last stage of a processed capture
    ENRICHED = "enriched"  # one background-enrichment job finished (tray count ticks down)


class ItemState(str, Enum):
    """Display state of one capture in the live queue view (independent of the fine-grained Stage)."""

    QUEUED = "queued"  # waiting in line behind the in-flight capture
    IN_FLIGHT = "in_flight"  # being processed right now (carries a live Stage)
    SAVED = "saved"  # committed to the vault
    DISCARDED = "discarded"  # reviewed and thrown away (raw kept in the inbox)
    FAILED = "failed"  # processing failed; nothing committed
    EMPTY = "empty"  # reached the worker with no text — dropped, never shown in history


# The ordered pipeline a capture walks while IN_FLIGHT; also the strip the queue view highlights.
_INFLIGHT_STAGES = frozenset(
    {Stage.CAPTURING, Stage.ANALYZING, Stage.AWAITING_REVIEW, Stage.COMMITTING}
)
# Terminal stages that fix a queue item's final display state (PROJECTION_FAILED = note WAS saved).
_TERMINAL_ITEM_STATE: dict[Stage, ItemState] = {
    Stage.SAVED: ItemState.SAVED,
    Stage.PROJECTION_FAILED: ItemState.SAVED,
    Stage.DISCARDED: ItemState.DISCARDED,
    Stage.FAILED: ItemState.FAILED,
    Stage.EMPTY: ItemState.EMPTY,
}
_RECENT_CAP = 5  # how many just-finished notes the queue view keeps as fading history


@dataclass(frozen=True)
class CaptureStatus:
    """A progress update for one capture: a stage plus an optional human-readable detail."""

    stage: Stage
    detail: str = ""
    pending: int = 0  # captures still queued behind this one (backpressure depth at emit time)


@dataclass(frozen=True)
class QueueItem:
    """One capture's place in the live queue view — an immutable snapshot the GUI renders.

    `state` is the display bucket (in-flight / queued / finished); `stage` is the live pipeline
    Stage while IN_FLIGHT (else None); `position` is the 1-based place in line for a QUEUED item
    (0 for the in-flight note and finished history)."""

    id: str
    snippet: str  # a one-line preview of the captured text
    source: str  # the Source.app that produced it (e.g. "phone", "grandplan") → the view's icon
    state: ItemState
    stage: Stage | None
    position: int
    detail: str = ""


@dataclass
class _TrackedItem:
    """Mutable descriptor mirroring one queued/in-flight capture (the `queue.Queue` can't be peeked).

    Created at enqueue, promoted to IN_FLIGHT when the worker pulls it, advanced by the pipeline
    stages, then moved to recent history. Only the coordinator mutates it, always under the items
    lock; the public `QueueItem` snapshot is an immutable copy so the GUI never sees it change."""

    id: str
    snippet: str
    source: str
    state: ItemState
    stage: Stage | None = None
    detail: str = ""

    def snapshot(self, position: int) -> QueueItem:
        return QueueItem(
            id=self.id,
            snippet=self.snippet,
            source=self.source,
            state=self.state,
            stage=self.stage,
            position=position,
            detail=self.detail,
        )


ReviewFn = Callable[[ReviewState], bool]
StatusFn = Callable[[CaptureStatus], None]
CommitHook = Callable[[Committed], None]
Clock = Callable[[], str]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _committing_detail(pending: PendingReview) -> str:
    """Human-readable COMMITTING detail: a status update / edit reads differently from a new note."""
    if pending.update is not None:
        return f"marking '{pending.update.target.title}' as {pending.update.status.value}"
    if pending.edit is not None:
        return f"editing '{pending.edit.target.title}' ({pending.edit.summary()})"
    return "saving the note"


def committed_note_id(result: Committed) -> str:
    """The id of the note a commit touched — a NEW note, or the target of a status update / edit.

    The reproject pass runs `reconcile_deletions` (tombstoning notes whose .md the user removed in
    Obsidian); the just-touched note MUST be protected so it is never mistaken for a user deletion.
    A new note exposes `result.note.id`; an update/edit touched an existing note (`result.target.id`).
    Previously only new notes were protected, so a capture-driven status update could silently
    tombstone the very note it had just updated (observed data loss)."""
    if isinstance(result, CaptureResult):
        return result.note.id
    if isinstance(result, (StatusUpdateResult, EditResult)):
        return result.target.id
    raise AssertionError(f"unhandled Committed variant: {type(result).__name__}")


def _saved_detail(result: Committed) -> str:
    """Human-readable SAVED detail for any outcome (an update/edit has no file path)."""
    if isinstance(result, StatusUpdateResult):
        return f"{result.target.title} → {result.status.value}"
    if isinstance(result, EditResult):
        return f"{result.target.title} edited"
    if isinstance(result, CaptureResult):
        return str(result.path)
    # Exhaustiveness guard: a new `Committed` variant must extend this (portable to py3.10, which
    # lacks typing.assert_never) — a clear failure here beats an AttributeError on a missing `.path`.
    raise AssertionError(f"unhandled Committed variant: {type(result).__name__}")


_SNIPPET_CHARS = 72  # one tooltip/popup line; the review dialog shows the full text right after


def snippet_of(text: str, limit: int = _SNIPPET_CHARS) -> str:
    """One status-line preview of the text being processed (US-7 transparency, pure).

    The ANALYZING stage is the longest and was fully opaque — the user could not tell WHICH text
    the model was chewing on. Whitespace (incl. newlines) collapses to single spaces so the
    tooltip stays one line; over `limit` it is cut with an ellipsis."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


# A single token meaning "process one capture"; identity is all that matters.
_REQUEST = object()


@dataclass(frozen=True)
class _AutoCapture:
    """A pre-composed capture that AUTO-APPROVES (no review dialog) — a remote/phone `/capture`
    routed through THIS coordinator so it serializes with hotkey/tray captures on the one worker
    (single writer, no cross-surface conflict). `source` overrides the coordinator's default so the
    note is provenance-tagged (e.g. app="phone")."""

    text: str
    source: Source | None = None


@dataclass(frozen=True)
class PendingReviewView:
    """A capture awaiting an approve/discard decision — what a review surface (the desktop dialog or
    the phone app) needs to show it and act on it. `id` is passed back to `approve_pending` /
    `discard_pending`; `state` is the same display DTO the desktop review dialog renders."""

    id: str
    state: ReviewState
    source: str  # provenance app (e.g. "phone" / "grandplan") → the surface's icon
    snippet: str


class _PendingDecision:
    """The worker's parked review decision, resolvable from any surface (first wins). Mutable: a
    surface flips `approved` and sets `event`, which wakes the worker waiting inside `_await_decision`."""

    def __init__(self, *, id: str, state: ReviewState, source: str, snippet: str) -> None:
        self.id = id
        self.state = state
        self.source = source
        self.snippet = snippet
        self.event = threading.Event()
        self.approved = False


class CaptureCoordinator:
    """Serializes capture requests through one worker, reporting progress at each stage."""

    def __init__(
        self,
        *,
        capturer: Capturer,
        organizer: Organizer,
        embedder: Embedder,
        reconciler: Reconciler,
        repo: NoteRepository,
        originals: OriginalStore,
        vault: VaultWriter,
        review: ReviewFn | None = None,
        source: Source,
        clock: Clock = _utc_now_iso,
        on_status: StatusFn | None = None,
        after_commit: CommitHook | None = None,
        detector: UpdateDetector | None = None,
        edit_detector: EditDetector | None = None,
        placer: Placer | None = None,
        enrich: Callable[[str], object] | None = None,
        max_pending: int = 16,
    ) -> None:
        if max_pending < 1:
            raise ValueError("max_pending must be >= 1")
        self._capturer = capturer
        self._organizer = organizer
        self._embedder = embedder
        self._reconciler = reconciler
        self._repo = repo
        self._originals = originals
        self._vault = vault
        self._review = review
        self._source = source
        self._clock = clock
        self._on_status = on_status
        self._after_commit = after_commit
        self._detector = detector  # PR-B: detect capture-driven status updates (None = off)
        self._edit_detector = edit_detector  # PR-C: detect capture-driven field edits (None = off)
        self._placer = placer  # PR-G: propose structural edges for a new note (None = off)
        self._max_pending = max_pending
        self._queue: queue.Queue[object] = queue.Queue(maxsize=max_pending)
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        # Background enrichment (#38): note ids waiting for the post-commit LLM links/placement
        # pass. Drained by the SAME worker thread, and only when the capture queue is idle — the
        # single-writer invariant (ADR-0006) holds and a queued capture always runs first.
        self._enrich = enrich  # None = enrichment off (non-fast runs derive links inline)
        self._enrich_backlog: deque[str] = deque()
        self._enrich_lock = threading.Lock()
        # Live queue view (US-7): descriptors mirroring the capture line so the GUI can render each
        # note's place in line + stage in real time. `_queued` tracks the Queue in FIFO lockstep,
        # `_inflight` is the note being processed, `_recent` is a small fading history of finished
        # notes. All three are guarded by `_items_lock`; snapshots are immutable copies.
        self._items_lock = threading.Lock()
        self._queued_items: deque[_TrackedItem] = deque()
        self._inflight: _TrackedItem | None = None
        self._recent: deque[_TrackedItem] = deque(maxlen=_RECENT_CAP)
        self._seq = itertools.count(1)  # monotonic ids (generated under _items_lock)
        # Shared review decision (mobile parity): when no synchronous `review` resolver is injected,
        # the worker parks the awaiting-review capture here so ANY surface — the desktop dialog OR a
        # phone `/api/pending` call — can approve/discard it (first wins). The commit still runs on the
        # worker (ADR-0006); a surface only sets the decision + wakes the worker.
        self._decision_lock = threading.Lock()
        self._decision: _PendingDecision | None = None

    # -- public API -----------------------------------------------------------------------------

    def submit(self) -> bool:
        """Capture the current selection NOW and enqueue it for review.

        Capturing at **enqueue** time (not when the worker later processes it) is what lets you fire
        several captures in a row — select → hotkey → select → hotkey → … — and have each keep its
        OWN text, reviewed one after another. (Reading the selection at process time made every queued
        press re-read whatever happened to be selected later.) Returns False if nothing is selected
        (emits EMPTY) or the buffer is full (emits REJECTED_BUSY). Thread-safe.
        """
        try:
            text = self._capturer.capture()
        except Exception as exc:  # noqa: BLE001 - a flaky capture backend must never crash the submitter
            # #6 audit: this used to swallow the backend error entirely — FAILED with no clue why.
            logger.exception("capture backend failed at submit")
            self._emit(Stage.FAILED, f"capture failed: {exc}")
            return False
        if not text or not text.strip():
            self._emit(Stage.EMPTY, "nothing new to capture — select text and press Ctrl+C first")
            return False
        return self._enqueue(text)

    def submit_text(self, text: str) -> bool:
        """Quick-capture: enqueue already-typed text (no selection needed). Returns False if the text
        is blank or the buffer is full. Same pipeline as `submit()` — only the source of the text
        differs — so the quick-capture popup is a thin Qt shell over this (the popup itself is a
        Windows adapter)."""
        if not text.strip():
            return False
        return self._enqueue(text)

    def submit_capture(self, text: str, *, source: Source | None = None) -> bool:
        """Enqueue a PRE-COMPOSED capture that AUTO-APPROVES (no review dialog) — a remote/phone
        `/capture` routed through this coordinator so it shares the ONE worker with hotkey/tray
        captures (single writer, no conflict). `source` provenance-tags the note (e.g. app="phone").
        Returns False if blank or the buffer is full. Thread-safe."""
        if not text.strip():
            return False
        return self._enqueue(_AutoCapture(text=text, source=source))

    def _enqueue(self, request: object) -> bool:
        # Put on the Queue and append the mirror descriptor atomically, so a snapshot never sees a
        # note in one but not the other (the worker removes from both front-first, keeping FIFO).
        with self._items_lock:
            try:
                self._queue.put_nowait(request)
            except queue.Full:
                item = None
            else:
                item = self._describe(request, ItemState.QUEUED)
                self._queued_items.append(item)
        if item is None:
            self._emit(
                Stage.REJECTED_BUSY,
                "a capture is already in progress — finish the current review first",
            )
            return False
        # Refresh the queue view the instant a note joins the line (not just on the next stage
        # change of the in-flight note). Not a notify-stage, so it stays tray-only, no popup.
        self._emit(Stage.QUEUED, item.snippet or "queued")
        return True

    def pending_count(self) -> int:
        """How many captures are queued waiting behind the one in flight (backpressure depth)."""
        return self._queue.qsize()

    def queue_snapshot(self) -> tuple[QueueItem, ...]:
        """An ordered, immutable view of the whole capture line for the live queue view (US-7).

        In-flight first (position 0, live stage), then the queued notes (positions 1..N in line),
        then the most-recently finished notes (position 0). Thread-safe; each item is a copy, so the
        GUI never holds a live descriptor that the worker could mutate under it."""
        with self._items_lock:
            rows: list[QueueItem] = []
            if self._inflight is not None:
                rows.append(self._inflight.snapshot(0))
            for position, item in enumerate(self._queued_items, start=1):
                rows.append(item.snapshot(position))
            rows.extend(item.snapshot(0) for item in self._recent)
            return tuple(rows)

    def _describe(self, request: object, state: ItemState) -> _TrackedItem:
        """Build a tracking descriptor from a queued request (id generated under _items_lock).

        A `_REQUEST` token reads the selection only when the worker runs it, so its snippet is
        filled in later (`_set_inflight_snippet`); str / _AutoCapture carry their text now."""
        if isinstance(request, _AutoCapture):
            text = request.text
            source = request.source.app if request.source is not None else self._source.app
        elif isinstance(request, str):
            text = request
            source = self._source.app
        else:  # _REQUEST sentinel — text not known until the worker reads the selection
            text = ""
            source = self._source.app
        return _TrackedItem(
            id=str(next(self._seq)),
            snippet=snippet_of(text) if text else "",
            source=source,
            state=state,
        )

    def _begin_inflight(self, request: object) -> None:
        """Promote the front queued descriptor (or synthesise one for a direct/test call) to in-flight."""
        with self._items_lock:
            if self._queued_items:
                item = self._queued_items.popleft()  # FIFO-matched to the Queue.get just done
            else:
                item = self._describe(request, ItemState.IN_FLIGHT)
            item.state = ItemState.IN_FLIGHT
            item.stage = None
            self._inflight = item

    def _set_inflight_snippet(self, text: str) -> None:
        """Fill the in-flight snippet once text is known (the `_REQUEST`/selection path)."""
        with self._items_lock:
            if self._inflight is not None and not self._inflight.snippet:
                self._inflight.snippet = snippet_of(text)

    def _track_stage(self, stage: Stage, detail: str) -> None:
        """Advance the in-flight descriptor (its live stage, or its final state). Called only for the
        pipeline's own transitions (`_advance`) — never for submit-path EMPTY/REJECTED_BUSY, which
        concern a *different* capture than the one the worker is processing."""
        with self._items_lock:
            item = self._inflight
            if item is None:
                return
            if stage in _TERMINAL_ITEM_STATE:
                item.state = _TERMINAL_ITEM_STATE[stage]
                item.stage = None  # finished — no longer walking the pipeline
                item.detail = detail
            elif stage in _INFLIGHT_STAGES:
                item.stage = stage
                item.detail = detail

    def _end_inflight(self) -> None:
        """Retire the in-flight descriptor into the fading history (dropping EMPTY no-ops)."""
        with self._items_lock:
            item = self._inflight
            self._inflight = None
            if item is not None and item.state in (
                ItemState.SAVED,
                ItemState.DISCARDED,
                ItemState.FAILED,
            ):
                self._recent.appendleft(item)  # most-recent first

    def _advance(self, stage: Stage, detail: str = "") -> None:
        """A pipeline transition of the in-flight note: track it, then emit (order matters — the
        snapshot must already reflect the new stage when the GUI repaints on this status)."""
        self._track_stage(stage, detail)
        self._emit(stage, detail)

    # -- review decision (multi-surface: desktop dialog OR phone; first wins) --------------------

    def _await_decision(self, pending: PendingReview) -> bool:
        """Block until this capture is approved (True) or discarded (False).

        An injected synchronous `review` resolver (tests, or a headless auto-policy) decides inline —
        unchanged behaviour. Otherwise the worker PARKS the decision so any surface — the desktop
        review dialog or a phone `/api/pending/<id>/approve|discard` call — can resolve it, whichever
        acts first. Shutting down mid-wait resolves as discard (the raw capture stays in the inbox).
        The commit itself still happens on the worker after this returns (ADR-0006 single writer).
        """
        if self._review is not None:
            return self._review(pending.state)
        with self._items_lock:
            item = self._inflight
            decision = _PendingDecision(
                id=item.id if item is not None else "",
                state=pending.state,
                source=item.source if item is not None else self._source.app,
                snippet=item.snippet if item is not None else "",
            )
        with self._decision_lock:
            self._decision = decision
        try:
            while not self._shutdown.is_set():
                if decision.event.wait(timeout=_POLL_INTERVAL):
                    return decision.approved
            return False  # shutting down → discard, keeping the raw capture in the inbox
        finally:
            with self._decision_lock:
                self._decision = None

    def pending_reviews(self) -> tuple[PendingReviewView, ...]:
        """The capture(s) currently awaiting an approve/discard decision (0 or 1). Thread-safe; the
        desktop dialog and the phone app both render this and act via `approve_pending`/`discard_pending`."""
        with self._decision_lock:
            decision = self._decision
            if decision is None:
                return ()
            return (
                PendingReviewView(
                    id=decision.id,
                    state=decision.state,
                    source=decision.source,
                    snippet=decision.snippet,
                ),
            )

    def approve_pending(self, pending_id: str) -> bool:
        """Approve the parked review with this id (from any surface). Returns True if it resolved this
        call, False if the id doesn't match the current pending review or it was already decided."""
        return self._resolve(pending_id, approved=True)

    def discard_pending(self, pending_id: str) -> bool:
        """Discard the parked review with this id (from any surface); the raw capture stays in the inbox."""
        return self._resolve(pending_id, approved=False)

    def _resolve(self, pending_id: str, *, approved: bool) -> bool:
        with self._decision_lock:
            decision = self._decision
            if decision is None or decision.id != pending_id or decision.event.is_set():
                return False  # nothing pending, wrong id, or another surface already decided
            decision.approved = approved
            decision.event.set()  # wake the worker blocked in _await_decision
            return True

    def submit_enrichment(self, note_id: str) -> bool:
        """Queue a committed note for the background links/placement pass (#38). Best-effort:
        returns False (and drops silently) when enrichment is off, the note is already queued, or
        the backlog is full — an unenriched note simply keeps its baseline links."""
        if self._enrich is None:
            return False
        with self._enrich_lock:
            if note_id in self._enrich_backlog or len(self._enrich_backlog) >= _ENRICH_BACKLOG_CAP:
                return False
            self._enrich_backlog.append(note_id)
            return True

    def enrichment_pending(self) -> int:
        """Notes still waiting for the background enrichment pass (for progress surfacing)."""
        with self._enrich_lock:
            return len(self._enrich_backlog)

    def run_one_enrichment(self) -> object | None:
        """Run the oldest queued enrichment job (worker-thread / test entry; same guard as
        `process_one`). Returns the job's outcome, or None when there was nothing to do. A failing
        job is logged and dropped — enrichment must never wedge the capture worker."""
        worker = self._thread
        if worker is not None and worker.is_alive() and threading.current_thread() is not worker:
            raise RuntimeError(
                "run_one_enrichment() is driven by the worker once start() is called"
            )
        if self._enrich is None:
            return None
        with self._enrich_lock:
            if not self._enrich_backlog:
                return None
            note_id = self._enrich_backlog.popleft()
        try:
            outcome: object | None = self._enrich(note_id)
            logger.info("background enrichment of %s: %s", note_id, outcome)
        except Exception:  # noqa: BLE001 - one bad enrichment must not kill the worker
            logger.exception("enrichment of %s failed", note_id)
            outcome = None
        # Success OR failure, the job is done — emit so the tray's backlog count ticks down live
        # (it used to refresh only on capture events, so "enriching 18 note(s)" froze forever).
        self._emit(Stage.ENRICHED, "ready")
        return outcome

    def capacity(self) -> int:
        """Max captures that may wait before submit() is rejected with REJECTED_BUSY."""
        return self._max_pending

    def process_one(self, timeout: float | None = None) -> Committed | None:
        """Process a single queued capture. Blocks up to `timeout` for one to arrive.

        Returns the committed result (a new note or a status update), or None if nothing was queued
        / it was discarded / empty / failed. Drives both the worker loop and the (thread-free) unit
        tests; once `start()` has
        spun the worker, only that worker may call it — concurrent external calls would race a
        second `_process()` over the (non-thread-safe) repo, so they are refused.
        """
        worker = self._thread
        if worker is not None and worker.is_alive() and threading.current_thread() is not worker:
            raise RuntimeError(
                "process_one() is driven by the worker once start() is called; "
                "use submit() instead of calling it concurrently"
            )
        try:
            if timeout is None:
                request = self._queue.get()
            else:
                request = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        return self._process(request)

    def start(self) -> None:
        """Start the background worker (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._worker, name="grandplan-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the worker to stop and wait for the in-flight capture to finish (safe anytime)."""
        self._shutdown.set()
        with self._decision_lock:  # wake a review parked in _await_decision so the worker can exit
            if self._decision is not None:
                self._decision.event.set()  # approved stays False → discard, raw kept in the inbox
        thread = self._thread
        if thread is not None:
            thread.join(timeout=_JOIN_TIMEOUT)
            # Only release the reference if the worker actually stopped. If the join timed out (e.g. a
            # stalled LLM call), the thread is still draining the queue — clearing the ref would let a
            # later start() spawn a SECOND worker racing the same non-thread-safe repo/vault. Keep the
            # ref so start() sees it alive and refuses to double-spawn (robustness fix).
            if not thread.is_alive():
                self._thread = None

    # -- internals ------------------------------------------------------------------------------

    def _worker(self) -> None:
        while not self._shutdown.is_set():
            self.process_one(timeout=_POLL_INTERVAL)
            # Idle-priority enrichment: only when no capture is queued (a capture submitted during
            # an enrichment's LLM call waits at most that one call — never a whole backlog).
            if self._queue.empty() and not self._shutdown.is_set():
                self.run_one_enrichment()

    def _process(self, request: object = _REQUEST) -> Committed | None:
        self._begin_inflight(request)  # this note is now the one being made (queue view)
        try:
            # Three request shapes, one pipeline: an _AutoCapture (remote/phone) carries pre-composed
            # text and AUTO-APPROVES (no dialog); a str (quick-capture) carries typed text; anything
            # else reads the current selection via the capturer. All commit through this one worker.
            auto_approve = False
            source = self._source
            if isinstance(request, _AutoCapture):
                self._advance(Stage.CAPTURING, "receiving a remote capture")
                text: str | None = request.text
                auto_approve = True
                if request.source is not None:
                    source = request.source
            elif isinstance(request, str):
                self._advance(Stage.CAPTURING, "capturing typed note")
                text = request
            else:
                self._advance(Stage.CAPTURING, "reading the selection")
                text = self._capturer.capture()
            if not text:
                self._advance(
                    Stage.EMPTY, "nothing new to capture — select text and press Ctrl+C first"
                )
                return None
            self._set_inflight_snippet(text)  # fill the queue-view snippet for the selection path
            # Show WHAT is being analyzed, not just that analysis is happening — this stage is
            # the longest (a full local-LLM call) and used to be a black box (US-7).
            self._advance(Stage.ANALYZING, f"organizing with local AI: “{snippet_of(text)}”")
            pending = start_review(
                text,
                created=self._clock(),
                source=source,
                organizer=self._organizer,
                embedder=self._embedder,
                reconciler=self._reconciler,
                repo=self._repo,
                originals=self._originals,
                detector=self._detector,
                edit_detector=self._edit_detector,
                placer=self._placer,
            )
            self._advance(Stage.AWAITING_REVIEW, pending.state.title)
            # A capture with `auto_approve` commits without a decision; otherwise the worker waits
            # for an approve/discard — resolved by a synchronous resolver, the desktop dialog, or a
            # phone call (whichever first) via `_await_decision`.
            if not auto_approve and not self._await_decision(pending):
                discard(pending)
                self._advance(Stage.DISCARDED, "discarded — raw capture kept in the inbox")
                return None
            self._advance(Stage.COMMITTING, _committing_detail(pending))
            result = approve(pending, repo=self._repo, vault=self._vault)
            self._advance(Stage.SAVED, _saved_detail(result))
            self._run_after_commit(result)
            return result
        except Exception as exc:  # noqa: BLE001 - one bad capture must not kill the worker
            logger.exception("capture failed")
            self._advance(Stage.FAILED, str(exc))
            return None
        finally:
            self._end_inflight()  # retire it into history BEFORE IDLE, so the snapshot is current
            self._emit(Stage.IDLE, "ready")

    def _run_after_commit(self, result: Committed) -> None:
        """Run the post-commit hook (e.g. plan/graph re-projection) without failing the save."""
        if self._after_commit is None:
            return
        try:
            self._after_commit(result)
        except Exception:  # noqa: BLE001 - the note is already saved; projection is best-effort
            logger.exception("post-commit projection failed")
            # Distinct from FAILED: the note IS committed; only the derived plan/graph is stale.
            self._advance(Stage.PROJECTION_FAILED, "note saved, but updating the plan failed")

    def _emit(self, stage: Stage, detail: str = "") -> None:
        logger.info("capture %s%s", stage.value, f": {detail}" if detail else "")
        if self._on_status is None:
            return
        try:
            self._on_status(CaptureStatus(stage=stage, detail=detail, pending=self._queue.qsize()))
        except Exception:  # noqa: BLE001 - a bad status listener must not break the worker
            logger.exception("on_status listener failed")
