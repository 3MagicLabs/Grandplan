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


@dataclass(frozen=True)
class CaptureStatus:
    """A progress update for one capture: a stage plus an optional human-readable detail."""

    stage: Stage
    detail: str = ""
    pending: int = 0  # captures still queued behind this one (backpressure depth at emit time)


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
            self._emit(Stage.EMPTY, "no text was selected")
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
        try:
            self._queue.put_nowait(request)
            return True
        except queue.Full:
            self._emit(
                Stage.REJECTED_BUSY,
                "a capture is already in progress — finish the current review first",
            )
            return False

    def pending_count(self) -> int:
        """How many captures are queued waiting behind the one in flight (backpressure depth)."""
        return self._queue.qsize()

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
        try:
            # Three request shapes, one pipeline: an _AutoCapture (remote/phone) carries pre-composed
            # text and AUTO-APPROVES (no dialog); a str (quick-capture) carries typed text; anything
            # else reads the current selection via the capturer. All commit through this one worker.
            auto_approve = False
            source = self._source
            if isinstance(request, _AutoCapture):
                self._emit(Stage.CAPTURING, "receiving a remote capture")
                text: str | None = request.text
                auto_approve = True
                if request.source is not None:
                    source = request.source
            elif isinstance(request, str):
                self._emit(Stage.CAPTURING, "capturing typed note")
                text = request
            else:
                self._emit(Stage.CAPTURING, "reading the selection")
                text = self._capturer.capture()
            if not text:
                self._emit(Stage.EMPTY, "no text was selected")
                return None
            # Show WHAT is being analyzed, not just that analysis is happening — this stage is
            # the longest (a full local-LLM call) and used to be a black box (US-7).
            self._emit(Stage.ANALYZING, f"organizing with local AI: “{snippet_of(text)}”")
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
            self._emit(Stage.AWAITING_REVIEW, pending.state.title)
            # A remote/phone capture commits without the desktop review dialog (you're away); a
            # desktop hotkey/quick capture waits for your approve/edit decision.
            if not auto_approve and not self._review(pending.state):
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
            self._on_status(CaptureStatus(stage=stage, detail=detail, pending=self._queue.qsize()))
        except Exception:  # noqa: BLE001 - a bad status listener must not break the worker
            logger.exception("on_status listener failed")
