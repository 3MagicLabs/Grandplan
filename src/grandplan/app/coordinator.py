"""CaptureCoordinator — serialize captures, surface progress, isolate failures (ADR-0006).

The tray GUI used to run the whole capture pipeline (local LLM + embeddings + the modal review
dialog) synchronously on the Qt main thread, inside `pragma: no cover` closures. A modal dialog
spins a nested event loop, so the trigger timer could *re-enter* and stack multiple concurrent
pipelines — exhausting memory — while also silently coalescing back-to-back captures into one.

This class extracts that orchestration into a **Qt-free, fully unit-tested** unit:

- **Serialized & bounded** — one worker thread drains a queue capped at `max_pending` (default 1):
  at most one capture in flight plus one queued; further `submit()`s are *rejected with a visible
  status*, never stacked or silently dropped. Serialization also means only one local-LLM call runs
  at a time (so the model runtime can't fan out into parallel copies).
- **Observable** — every stage is logged and emitted as a `CaptureStatus` to an injected `on_status`
  callback (the GUI maps it to the tray tooltip/notifications).
- **Off the UI thread** — all heavy work runs on the worker; the only main-thread step is the
  injected `review(state) -> bool` decision (the GUI marshals it; tests pass a plain function).
- **Fault-isolated** — one capture's failure is reported as `FAILED`; the worker keeps serving.

It reuses the tested `app.review` controller — it adds *coordination*, not pipeline logic.
"""

from __future__ import annotations

import logging
import queue
import threading
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


class Stage(str, Enum):
    """A point in one capture's lifecycle, emitted for visibility (US-7)."""

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


@dataclass(frozen=True)
class CaptureStatus:
    """A progress update for one capture: a stage plus an optional human-readable detail."""

    stage: Stage
    detail: str = ""


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


# A single token meaning "process one capture"; identity is all that matters.
_REQUEST = object()


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
        review: ReviewFn,
        source: Source,
        clock: Clock = _utc_now_iso,
        on_status: StatusFn | None = None,
        after_commit: CommitHook | None = None,
        detector: UpdateDetector | None = None,
        edit_detector: EditDetector | None = None,
        placer: Placer | None = None,
        max_pending: int = 1,
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
        self._queue: queue.Queue[object] = queue.Queue(maxsize=max_pending)
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None

    # -- public API -----------------------------------------------------------------------------

    def submit(self) -> bool:
        """Request a capture. Returns False (and emits REJECTED_BUSY) if the buffer is full.

        Thread-safe: called from the global-hotkey thread and the tray menu alike.
        """
        try:
            self._queue.put_nowait(_REQUEST)
            return True
        except queue.Full:
            self._emit(
                Stage.REJECTED_BUSY,
                "a capture is already in progress — finish the current review first",
            )
            return False

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
                self._queue.get()
            else:
                self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        return self._process()

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

    def _process(self) -> Committed | None:
        try:
            self._emit(Stage.CAPTURING, "reading the selection")
            text = self._capturer.capture()
            if not text:
                self._emit(Stage.EMPTY, "no text was selected")
                return None
            self._emit(Stage.ANALYZING, "organizing with local AI")
            pending = start_review(
                text,
                created=self._clock(),
                source=self._source,
                organizer=self._organizer,
                embedder=self._embedder,
                reconciler=self._reconciler,
                repo=self._repo,
                originals=self._originals,
                detector=self._detector,
                edit_detector=self._edit_detector,
                placer=self._placer,
            )
            self._emit(Stage.AWAITING_REVIEW, pending.state.title)
            if not self._review(pending.state):
                discard(pending)
                self._emit(Stage.DISCARDED, "discarded — raw capture kept in the inbox")
                return None
            self._emit(Stage.COMMITTING, _committing_detail(pending))
            result = approve(pending, repo=self._repo, vault=self._vault)
            self._emit(Stage.SAVED, _saved_detail(result))
            self._run_after_commit(result)
            return result
        except Exception as exc:  # noqa: BLE001 - one bad capture must not kill the worker
            logger.exception("capture failed")
            self._emit(Stage.FAILED, str(exc))
            return None
        finally:
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
            self._emit(Stage.PROJECTION_FAILED, "note saved, but updating the plan failed")

    def _emit(self, stage: Stage, detail: str = "") -> None:
        logger.info("capture %s%s", stage.value, f": {detail}" if detail else "")
        if self._on_status is None:
            return
        try:
            self._on_status(CaptureStatus(stage=stage, detail=detail))
        except Exception:  # noqa: BLE001 - a bad status listener must not break the worker
            logger.exception("on_status listener failed")
