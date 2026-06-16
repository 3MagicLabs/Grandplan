"""Tests for the review view-model (start_review / approve / discard)."""

from __future__ import annotations

from pathlib import Path

from grandplan.app.review import approve, discard, start_review
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Source
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore

_SOURCE = Source(app="grandplan", title="capture")
_CREATED = "2026-06-15T00:00:00Z"


def _start(text: str, repo: InMemoryNoteRepository, originals: InMemoryOriginalStore):  # type: ignore[no-untyped-def]
    return start_review(
        text,
        created=_CREATED,
        source=_SOURCE,
        organizer=HeuristicOrganizer(),
        embedder=HashingEmbedder(),
        reconciler=SimilarityReconciler(),
        repo=repo,
        originals=originals,
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
    assert any(
        (edge.source_id, edge.target_id) == (second.note.id, first.note.id) for edge in repo.edges()
    )
