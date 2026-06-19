"""Tests for the review view-model (start_review / approve / discard)."""

from __future__ import annotations

from pathlib import Path

from grandplan.app.review import EditResult, StatusUpdateResult, approve, discard, start_review
from grandplan.core.edit_detect import EditDetector, HeuristicEditDetector
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import NoteEdit, NoteStatus, Source
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
    edit_detector: EditDetector | None = None,
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
        edit_detector=edit_detector,
    )


def test_start_review_shows_state_without_committing() -> None:
    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    pending = _start("TODO call the dentist", repo, originals)
    assert pending.state.title == "TODO call the dentist"
    assert pending.state.note_type == "task"
    assert repo.notes() == ()  # nothing committed yet
    assert originals.get(pending.original.id) is not None  # captured to the inbox


def test_placement_proposes_and_records_structural_edge_on_approve(tmp_path: Path) -> None:
    # PR-G: a new capture is placed under a similar, more-abstract existing note; approve records
    # the part_of edge (append-only — no note mutated).
    from grandplan.core.models import EdgeKind, Horizon, Note, NoteType
    from grandplan.core.placement import HeuristicPlacer
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    emb = HashingEmbedder()
    goal = Note(
        id="g",
        original_id="og",
        title="ship the analytics product roadmap",
        body="b",
        type=NoteType.GOAL,
        horizon=Horizon.GOAL,
    )
    repo.add_note(goal, emb.embed("ship the analytics product roadmap"))

    pending = start_review(
        "ship the analytics product launch checklist task",
        created=_CREATED,
        source=_SOURCE,
        organizer=HeuristicOrganizer(),
        embedder=emb,
        reconciler=SimilarityReconciler(),
        repo=repo,
        originals=originals,
        placer=HeuristicPlacer(part_of_threshold=0.15),
    )
    assert pending.placement is not None and pending.placement.parent_id == "g"

    result = approve(pending, repo=repo, vault=vault)
    assert isinstance(result, CaptureResult)
    assert any(
        e.source_id == result.note.id and e.target_id == "g" and e.kind is EdgeKind.PART_OF
        for e in repo.edges()
    )


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


def test_status_update_event_carries_the_capture_timestamp(tmp_path: Path) -> None:
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
    approve(pending, repo=repo, vault=vault)
    (event,) = [e for e in repo.history_of(first.note.id) if e.kind == "status"]
    assert (
        event.at == _CREATED
    )  # the event is stamped with the capture's `created` (no hidden clock)


# -- PR-C: capture-driven edits -----------------------------------------------------------------


def test_edit_capture_proposes_and_applies_an_edit_event(tmp_path: Path) -> None:
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    first = approve(_start(_TASK, repo, originals), repo=repo, vault=vault)
    assert isinstance(first, CaptureResult)

    pending = _start(
        "rename the bug bounty finder tool to bounty hunter",
        repo,
        originals,
        edit_detector=HeuristicEditDetector(),
    )
    assert pending.edit is not None
    assert pending.edit.target.id == first.note.id
    assert pending.edit.edit == NoteEdit(title="bounty hunter")
    assert pending.state.is_edit and pending.state.edit_target_title == first.note.title
    assert "title → bounty hunter" in pending.state.edit_summary

    result = approve(pending, repo=repo, vault=vault)
    assert isinstance(result, EditResult)
    current = repo.current_note(first.note.id)
    assert current is not None and current.title == "bounty hunter"
    assert len(repo.notes()) == 1  # an edit is an event, not a new note
    (event,) = [e for e in repo.history_of(first.note.id) if e.kind == "edit"]
    assert event.at == _CREATED


def test_edit_that_would_not_change_the_note_proposes_nothing(tmp_path: Path) -> None:
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    first = approve(_start(_TASK, repo, originals), repo=repo, vault=vault)
    assert isinstance(first, CaptureResult)
    title = first.note.title  # the note's current title

    # An edit capture whose new title equals the current title → no derived change → no proposal.
    pending = _start(
        f"rename it to {title}", repo, originals, edit_detector=HeuristicEditDetector()
    )
    assert pending.edit is None  # idempotent: nothing to change


def test_status_intent_takes_precedence_over_edit(tmp_path: Path) -> None:
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    approve(_start(_TASK, repo, originals), repo=repo, vault=vault)

    pending = _start(
        "done building the bug bounty finder tool",
        repo,
        originals,
        detector=HeuristicUpdateDetector(),
        edit_detector=HeuristicEditDetector(),
    )
    assert pending.update is not None  # status wins
    assert pending.edit is None


def test_edit_intent_without_match_falls_back_to_new_note(tmp_path: Path) -> None:
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    approve(_start(_TASK, repo, originals), repo=repo, vault=vault)

    pending = _start(
        "rename the grocery list to weekly shopping",
        repo,
        originals,
        edit_detector=HeuristicEditDetector(),
    )
    assert pending.edit is None  # no confident match → normal new-note flow
    result = approve(pending, repo=repo, vault=vault)
    assert isinstance(result, CaptureResult)
    assert len(repo.notes()) == 2


def test_approve_applies_proposed_status_changes_to_existing_notes(tmp_path: Path) -> None:
    # Slice B: a new note implies an existing related task is done → approving the review applies
    # that status change to the EXISTING note as an append-only event (the note is never mutated).
    from grandplan.core.models import Note, NoteType
    from grandplan.core.reconcile import (
        ReconcileProposal,
        Reconciler,
        RelatedCandidate,
        Relationship,
    )
    from grandplan.core.vault import MarkdownVaultWriter

    repo, originals = InMemoryNoteRepository(), InMemoryOriginalStore()
    emb = HashingEmbedder()
    existing = Note(
        id="task1", original_id="oe", title="Build the API", body="b", type=NoteType.TASK
    )
    repo.add_note(existing, emb.embed("build the api"))

    class StubReconciler:  # proposes marking the existing task done
        def reconcile(self, proposed, embedding, repo) -> ReconcileProposal:  # type: ignore[no-untyped-def]
            return ReconcileProposal(
                (
                    RelatedCandidate(
                        note=existing,
                        score=0.9,
                        relationship=Relationship.RELATED,
                        suggested_status=NoteStatus.DONE,
                    ),
                )
            )

    reconciler: Reconciler = StubReconciler()
    pending = start_review(
        "wrote up the API design now that the build is finished",
        created=_CREATED,
        source=_SOURCE,
        organizer=HeuristicOrganizer(),
        embedder=emb,
        reconciler=reconciler,
        repo=repo,
        originals=originals,
    )
    assert pending.state.proposed_updates == (("Build the API", "done"),)  # surfaced for review

    result = approve(pending, repo=repo, vault=MarkdownVaultWriter(tmp_path / "vault"))
    assert isinstance(result, CaptureResult)  # the new note was still created
    assert repo.status_of("task1") is NoteStatus.DONE  # the EXISTING note was updated (append-only)
