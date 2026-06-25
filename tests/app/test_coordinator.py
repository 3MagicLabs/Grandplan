"""Tests for the CaptureCoordinator: serialization, observability, fault isolation.

The coordinator is Qt-free by design (ADR-0006), so the whole capture lifecycle is exercised
here with fast offline fakes — no Windows/Qt needed. `process_one()` runs one capture
synchronously (deterministic); `start()/stop()` run the same logic on a worker thread.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from grandplan.app.coordinator import (
    CaptureCoordinator,
    CaptureStatus,
    Stage,
    committed_note_id,
)
from grandplan.app.review import EditResult, ReviewState, StatusUpdateResult
from grandplan.core.edit_detect import HeuristicEditDetector
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import NoteStatus, Source
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.pipeline import CaptureResult
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore
from grandplan.core.update_detect import HeuristicUpdateDetector
from grandplan.core.vault import MarkdownVaultWriter

_SOURCE = Source(app="grandplan", title="capture")


class SeqCapturer:
    """A capturer that returns a preset sequence of selections (None/'' = nothing selected)."""

    def __init__(self, selections: list[str | None]) -> None:
        self._selections = list(selections)
        self.calls = 0

    def capture(self) -> str | None:
        self.calls += 1
        return self._selections.pop(0) if self._selections else None


class BoomCapturer:
    """A capturer that always raises — to prove one failure can't kill the coordinator."""

    def capture(self) -> str | None:
        raise RuntimeError("capture backend exploded")


def _make(
    tmp_path: Path,
    *,
    capturer: object,
    review,  # type: ignore[no-untyped-def]
    on_status=None,  # type: ignore[no-untyped-def]
    after_commit=None,  # type: ignore[no-untyped-def]
    detector=None,  # type: ignore[no-untyped-def]
    edit_detector=None,  # type: ignore[no-untyped-def]
    max_pending: int = 1,
) -> tuple[CaptureCoordinator, InMemoryNoteRepository, InMemoryOriginalStore]:
    repo = InMemoryNoteRepository()
    originals = InMemoryOriginalStore()
    coord = CaptureCoordinator(
        capturer=capturer,  # type: ignore[arg-type]
        organizer=HeuristicOrganizer(),
        embedder=HashingEmbedder(),
        reconciler=SimilarityReconciler(),
        repo=repo,
        originals=originals,
        vault=MarkdownVaultWriter(tmp_path / "vault"),
        review=review,
        source=_SOURCE,
        clock=lambda: "2026-06-16T00:00:00+00:00",
        on_status=on_status,
        after_commit=after_commit,
        detector=detector,
        edit_detector=edit_detector,
        max_pending=max_pending,
    )
    return coord, repo, originals


def _stages(statuses: list[CaptureStatus]) -> list[Stage]:
    return [status.stage for status in statuses]


def test_submit_text_captures_typed_input_without_a_selection(tmp_path: Path) -> None:
    # Quick-capture (P0): typed text runs through the SAME pipeline, bypassing the selection capturer.
    coord, repo, _ = _make(
        tmp_path,
        capturer=SeqCapturer([None]),  # selection capturer returns nothing — must be ignored
        review=lambda state: True,
    )
    assert coord.submit_text("buy milk and call the bank") is True
    result = coord.process_one(timeout=0)
    assert result is not None  # committed (not EMPTY — the typed text was used)
    assert result.original.text == "buy milk and call the bank"  # verbatim typed text preserved
    assert len(repo.notes()) == 1


def test_submit_text_rejects_blank_input(tmp_path: Path) -> None:
    coord, _, _ = _make(tmp_path, capturer=SeqCapturer([None]), review=lambda state: True)
    assert coord.submit_text("   ") is False  # nothing to capture


def test_approve_commits_writes_vault_and_reports_full_stage_sequence(tmp_path: Path) -> None:
    statuses: list[CaptureStatus] = []
    committed: list[object] = []
    coord, repo, originals = _make(
        tmp_path,
        capturer=SeqCapturer(["TODO call the dentist"]),
        review=lambda state: True,
        on_status=statuses.append,
        after_commit=committed.append,
    )

    assert coord.submit() is True
    result = coord.process_one(timeout=0)

    assert result is not None
    assert repo.get_note(result.note.id) is not None
    assert result.path.exists()
    assert originals.get(result.original.id) is not None  # captured to the inbox
    assert len(committed) == 1  # after_commit (e.g. re-projection) ran exactly once
    assert _stages(statuses) == [
        Stage.CAPTURING,
        Stage.ANALYZING,
        Stage.AWAITING_REVIEW,
        Stage.COMMITTING,
        Stage.SAVED,
        Stage.IDLE,
    ]


def test_capture_driven_status_update_applies_event_without_new_note(tmp_path: Path) -> None:
    """PR-B: an update capture matches the existing note and (on approve) flips its derived status
    via a `status` event — no second note, full stage sequence, after_commit re-projection runs."""
    statuses: list[CaptureStatus] = []
    committed: list[object] = []
    coord, repo, _ = _make(
        tmp_path,
        capturer=SeqCapturer(
            ["build the bug bounty finder tool", "done building the bug bounty finder tool"]
        ),
        review=lambda state: True,
        on_status=statuses.append,
        after_commit=committed.append,
        detector=HeuristicUpdateDetector(),
    )

    coord.submit()
    first = coord.process_one(timeout=0)
    coord.submit()
    second = coord.process_one(timeout=0)

    assert isinstance(first, CaptureResult)
    assert isinstance(second, StatusUpdateResult)
    assert repo.status_of(first.note.id) is NoteStatus.DONE  # event-sourced status applied
    assert len(repo.notes()) == 1  # the update added NO note
    # The reproject must PROTECT the note the update touched (else reconcile_deletions could
    # tombstone the very note we just updated — the observed "marked done and then deleted" loss).
    assert committed_note_id(first) == first.note.id
    assert committed_note_id(second) == first.note.id
    assert len(committed) == 2  # re-projection ran for the note AND the update
    stages = _stages(statuses)
    assert stages[-1] is Stage.IDLE
    assert stages.count(Stage.SAVED) == 2  # both the create and the update report SAVED


def test_capture_driven_edit_applies_event_without_new_note(tmp_path: Path) -> None:
    """PR-C: an edit capture matches the existing note and (on approve) records an `edit` event —
    no second note, the derived note reflects the edit, after_commit re-projection runs."""
    statuses: list[CaptureStatus] = []
    committed: list[object] = []
    coord, repo, _ = _make(
        tmp_path,
        capturer=SeqCapturer(
            [
                "build the bug bounty finder tool",
                "rename the bug bounty finder tool to bounty hunter",
            ]
        ),
        review=lambda state: True,
        on_status=statuses.append,
        after_commit=committed.append,
        edit_detector=HeuristicEditDetector(),
    )

    coord.submit()
    first = coord.process_one(timeout=0)
    coord.submit()
    second = coord.process_one(timeout=0)

    assert isinstance(first, CaptureResult)
    assert isinstance(second, EditResult)
    assert committed_note_id(second) == first.note.id  # the edit protects the note it touched
    current = repo.current_note(first.note.id)
    assert current is not None and current.title == "bounty hunter"  # edit applied (derived)
    assert len(repo.notes()) == 1  # the edit added NO note
    assert len(committed) == 2  # re-projection ran for the note AND the edit
    assert _stages(statuses)[-1] is Stage.IDLE


def test_discard_writes_nothing_but_keeps_inbox(tmp_path: Path) -> None:
    statuses: list[CaptureStatus] = []
    committed: list[object] = []
    coord, repo, originals = _make(
        tmp_path,
        capturer=SeqCapturer(["a throwaway thought"]),
        review=lambda state: False,
        on_status=statuses.append,
        after_commit=committed.append,
    )

    assert coord.submit() is True
    result = coord.process_one(timeout=0)

    assert result is None
    assert repo.notes() == ()  # nothing committed (US-4)
    assert originals.all()  # raw capture retained in the inbox
    assert committed == []  # no commit -> no re-projection
    assert _stages(statuses) == [
        Stage.CAPTURING,
        Stage.ANALYZING,
        Stage.AWAITING_REVIEW,
        Stage.DISCARDED,
        Stage.IDLE,
    ]


def test_empty_selection_skips_review_entirely(tmp_path: Path) -> None:
    statuses: list[CaptureStatus] = []
    reviewed: list[ReviewState] = []
    coord, repo, _ = _make(
        tmp_path,
        capturer=SeqCapturer([None]),
        review=lambda state: reviewed.append(state) or True,
        on_status=statuses.append,
    )

    # Capture happens at submit() now, so an empty selection is rejected there (nothing enqueued).
    assert coord.submit() is False
    assert reviewed == []  # never prompted the user
    assert repo.notes() == ()
    assert _stages(statuses) == [Stage.EMPTY]


def test_failure_is_isolated_reported_and_coordinator_survives(tmp_path: Path) -> None:
    statuses: list[CaptureStatus] = []
    coord, repo, _ = _make(
        tmp_path,
        capturer=BoomCapturer(),
        review=lambda state: True,
        on_status=statuses.append,
    )

    # A failing capture backend must not raise out of submit(); it's reported as FAILED, nothing
    # is enqueued, and the coordinator stays usable for the next press.
    assert coord.submit() is False
    assert Stage.FAILED in _stages(statuses)
    assert repo.notes() == ()
    assert coord.submit() is False  # still usable (no crash) — the capturer is still failing


def test_several_captures_each_keep_their_own_text(tmp_path: Path) -> None:
    # Issue: firing several captures in a row (select → hotkey → select → hotkey) must keep each
    # one's OWN selection — submit() captures at enqueue, so they don't all re-read a later selection.
    coord, repo, _ = _make(
        tmp_path,
        capturer=SeqCapturer(["first idea", "second idea", "third idea"]),
        review=lambda state: True,
        max_pending=8,
    )
    assert coord.submit() and coord.submit() and coord.submit()  # three distinct selections queued
    results = [coord.process_one(timeout=0) for _ in range(3)]

    assert all(isinstance(r, CaptureResult) for r in results)
    titles = {repo.current_note(r.note.id).title for r in results}  # type: ignore[union-attr]
    assert titles == {"first idea", "second idea", "third idea"}  # each note kept its own text
    assert len(repo.notes()) == 3  # all three have a place — none lost or merged


def test_submit_serializes_and_rejects_overflow_then_processes_in_order(tmp_path: Path) -> None:
    """The core concurrency fix: one in flight + one queued; a third is rejected, not stacked.

    Deterministic (no threads): we probe the queue from *inside* the review of capture #1, which
    is exactly the window the old code re-entered and stacked work.
    """
    statuses: list[CaptureStatus] = []
    submit_results: list[bool] = []
    probed = {"done": False}

    def review(state: ReviewState) -> bool:
        # Probe only while capture #1 is in flight (it's already been dequeued, queue empty):
        # a submit fills the 1-deep buffer (#2), the next overflows it (#3 rejected, BUSY).
        if not probed["done"]:
            probed["done"] = True
            submit_results.append(coord.submit())  # -> True (queued)
            submit_results.append(coord.submit())  # -> False (rejected, visible BUSY status)
        return True

    coord, repo, _ = _make(
        tmp_path,
        capturer=SeqCapturer(["first note", "second note", "third note"]),
        review=review,
        on_status=statuses.append,
    )

    coord.submit()  # enqueue #1
    first = coord.process_one(timeout=0)  # dequeues #1; review probes mid-flight
    second = coord.process_one(timeout=0)  # the one queued during #1, processed in order

    assert submit_results == [True, False]  # 2nd accepted (queued), 3rd rejected (busy)
    assert Stage.REJECTED_BUSY in _stages(statuses)
    assert first is not None and second is not None
    assert {note.title for note in repo.notes()} == {"first note", "second note"}  # 3rd never ran


def test_after_commit_failure_keeps_note_and_reports_projection_failed(tmp_path: Path) -> None:
    """A failing post-commit hook (e.g. re-projection) must not lose the saved note, and must be
    reported as PROJECTION_FAILED — distinct from a capture FAILED."""
    statuses: list[CaptureStatus] = []

    def boom_after_commit(_result: object) -> None:
        raise RuntimeError("projection blew up")

    coord, repo, _ = _make(
        tmp_path,
        capturer=SeqCapturer(["keep me", "still alive"]),  # 2nd value for the survival re-submit
        review=lambda state: True,
        on_status=statuses.append,
        after_commit=boom_after_commit,
    )

    assert coord.submit() is True
    result = coord.process_one(timeout=0)

    assert result is not None
    assert repo.get_note(result.note.id) is not None  # the note IS saved
    stages = _stages(statuses)
    assert stages.index(Stage.SAVED) < stages.index(Stage.PROJECTION_FAILED)  # saved, then warned
    assert Stage.FAILED not in stages  # NOT a capture failure
    assert stages[-1] is Stage.IDLE
    assert coord.submit() is True  # coordinator survives


def test_process_one_refused_while_worker_running(tmp_path: Path) -> None:
    """Once the worker is live it is the sole consumer; a concurrent external process_one() that
    would race a second _process() over the non-thread-safe repo is refused."""
    coord, _, _ = _make(tmp_path, capturer=SeqCapturer([]), review=lambda state: True)
    coord.start()
    try:
        with pytest.raises(RuntimeError, match="worker"):
            coord.process_one(timeout=0)
    finally:
        coord.stop()


def test_worker_thread_processes_submissions_in_order(tmp_path: Path) -> None:
    coord, repo, _ = _make(
        tmp_path,
        capturer=SeqCapturer(["alpha note", "beta note"]),
        review=lambda state: True,
    )
    coord.start()
    try:
        assert coord.submit() is True
        _wait_until(lambda: len(repo.notes()) >= 1)
        assert coord.submit() is True
        _wait_until(lambda: len(repo.notes()) >= 2)
    finally:
        coord.stop()

    assert {note.title for note in repo.notes()} == {"alpha note", "beta note"}


def test_start_is_idempotent_and_stop_is_safe_without_start(tmp_path: Path) -> None:
    coord, _, _ = _make(tmp_path, capturer=SeqCapturer([]), review=lambda state: True)
    coord.stop()  # no-op before start
    coord.start()
    coord.start()  # idempotent
    coord.stop()


def _wait_until(predicate, timeout: float = 5.0) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met within timeout")


# Guard against accidental import-time threading surprises.
assert threading.active_count() >= 1


def test_stop_keeps_worker_reference_when_join_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Robustness: if stop()'s join times out (a stalled worker), the thread ref must be KEPT so a
    # later start() can't spawn a second worker racing the same non-thread-safe state.
    import grandplan.app.coordinator as coordinator_module

    monkeypatch.setattr(coordinator_module, "_JOIN_TIMEOUT", 0.05)
    release = threading.Event()

    def blocking_review(state: ReviewState) -> bool:
        release.wait(2.0)  # hold the worker inside the review decision
        return False

    coord, _, _ = _make(
        tmp_path, capturer=SeqCapturer(["a note to review"]), review=blocking_review
    )
    coord.start()
    assert coord.submit()
    time.sleep(0.3)  # let the worker reach the blocking review

    coord.stop()  # join times out — the worker is still blocked
    assert coord._thread is not None  # ref kept → no double-spawn on a later start()

    release.set()  # release the worker so it can finish and observe the shutdown flag
    coord.stop()
    assert coord._thread is None  # clean stop now clears the ref
