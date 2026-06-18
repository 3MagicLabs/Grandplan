"""Tests for the review view-model (start_review / approve / discard)."""

from __future__ import annotations

from pathlib import Path

from grandplan.app.review import StatusUpdateResult, approve, discard, start_review
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import NoteStatus, Source
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.pipeline import CaptureResult
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore
from grandplan.core.update_detect import HeuristicUpdateDetector

_SOURCE = Source(app="grandplan", title="capture")
_CREATED = "2026-06-15T00:00:00Z"


def _start(  # type: ignore[no-untyped-def]
    text: str,
    repo: InMemoryNoteRepository,
    originals: InMemoryOriginalStore,
    *,
    detector: HeuristicUpdateDetector | None = None,
):
    return start_review(
        text,
        created=_CREATED,
        source=_SOURCE,
        organizer=HeuristicOrganizer(),
        embedder=HashingEmbedder(),
        reconciler=SimilarityReconciler(),
        repo=repo,
        originals=originals,
        detector=detector,
    )


def test_start_review_shows_state_without_committing() -> None:
    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    pending = _start("TODO call the dentist", repo, originals)
    assert pending.state.title == "TODO call the dentist"
    assert pending.state.note_type == "task"
    assert repo.notes() == ()  # nothing committed yet
    assert originals.get(pending.original.id) is not None  # captured to the inbox


def test_approve_commits_and_writes_vault(tmp_path: Path) -> None:
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    pending = _start("a useful idea worth keeping", repo, originals)
    result = approve(pending, repo=repo, vault=vault)
    assert repo.get_note(result.note.id) is not None
    assert result.path.exists()


def test_discard_writes_nothing() -> None:
    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    pending = _start("a throwaway thought", repo, originals)
    discard(pending)
    assert repo.notes() == ()
    assert originals.get(pending.original.id) is not None  # raw capture retained


def test_approve_links_detected_related_notes(tmp_path: Path) -> None:
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    vault = MarkdownVaultWriter(tmp_path / "vault")

    first = approve(
        _start("machine learning notes about neural networks", repo, originals),
        repo=repo,
        vault=vault,
    )
    pending = _start("neural networks and deep learning study", repo, originals)
    assert pending.state.related_titles  # related note detected
    second = approve(pending, repo=repo, vault=vault, link_related=True)
    assert isinstance(second, CaptureResult)
    assert any(
        (edge.source_id, edge.target_id) == (second.note.id, first.note.id) for edge in repo.edges()
    )


# -- PR-B: capture-driven status updates --------------------------------------------------------

_TASK = "build the bug bounty finder tool"


def test_update_capture_proposes_status_change_on_matched_note(tmp_path: Path) -> None:
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    first = approve(_start(_TASK, repo, originals), repo=repo, vault=vault)
    assert isinstance(first, CaptureResult)

    pending = _start(
        "done building the bug bounty finder tool",
        repo,
        originals,
        detector=HeuristicUpdateDetector(),
    )
    # The capture is recognised as an update to the existing note (not a new idea).
    assert pending.update is not None
    assert pending.update.target.id == first.note.id
    assert pending.update.status is NoteStatus.DONE
    assert pending.state.is_status_update
    assert pending.state.update_target_title == first.note.title
    assert pending.state.update_status == "done"


def test_approve_update_appends_status_event_and_creates_no_new_note(tmp_path: Path) -> None:
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    first = approve(_start(_TASK, repo, originals), repo=repo, vault=vault)
    assert isinstance(first, CaptureResult)

    pending = _start(
        "done building the bug bounty finder tool",
        repo,
        originals,
        detector=HeuristicUpdateDetector(),
    )
    result = approve(pending, repo=repo, vault=vault)

    assert isinstance(result, StatusUpdateResult)
    assert result.target.id == first.note.id and result.status is NoteStatus.DONE
    assert repo.status_of(first.note.id) is NoteStatus.DONE  # event-sourced status applied
    assert len(repo.notes()) == 1  # NO duplicate note — the update is an event, not a note
    assert originals.get(pending.original.id) is not None  # raw capture retained (lossless)


def test_update_intent_without_confident_match_falls_back_to_new_note(tmp_path: Path) -> None:
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    approve(_start(_TASK, repo, originals), repo=repo, vault=vault)

    # Update-intent ("done"), but about something unrelated → no confident match → normal new note.
    pending = _start(
        "done with the grocery shopping",
        repo,
        originals,
        detector=HeuristicUpdateDetector(),
    )
    assert pending.update is None
    result = approve(pending, repo=repo, vault=vault)
    assert isinstance(result, CaptureResult)
    assert len(repo.notes()) == 2  # a brand-new note was created, nothing was mutated


def test_update_to_note_already_in_target_status_proposes_nothing(tmp_path: Path) -> None:
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    first = approve(_start(_TASK, repo, originals), repo=repo, vault=vault)
    assert isinstance(first, CaptureResult)
    repo.set_status(first.note.id, NoteStatus.DONE)

    pending = _start(
        "done building the bug bounty finder tool",
        repo,
        originals,
        detector=HeuristicUpdateDetector(),
    )
    assert pending.update is None  # already DONE → no change to propose (idempotent)


def test_no_detector_means_no_update_detection(tmp_path: Path) -> None:
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    approve(_start(_TASK, repo, originals), repo=repo, vault=vault)

    pending = _start("done building the bug bounty finder tool", repo, originals)  # detector=None
    assert pending.update is None
    assert not pending.state.is_status_update
