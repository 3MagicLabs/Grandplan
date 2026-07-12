"""Tests for relink_notes — adding missing similarity edges between existing notes (append-only)."""

from __future__ import annotations

from grandplan.core.models import Note, NoteType
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.relink import relink_notes
from grandplan.core.repository import InMemoryNoteRepository


def _note(note_id: str, title: str) -> Note:
    return Note(id=note_id, original_id=f"o-{note_id}", title=title, body="b", type=NoteType.IDEA)


def test_relink_connects_similar_but_unlinked_notes() -> None:
    # Two notes with the SAME embedding are similar but were never linked (e.g. imported). relink
    # adds the edge; a note never links to itself.
    repo = InMemoryNoteRepository()
    repo.add_note(_note("a", "Alpha"), (1.0, 0.0))
    repo.add_note(_note("b", "Beta"), (0.6, 0.8))  # cosine 0.6 → RELATED band (not a duplicate)
    assert repo.edges() == ()  # start disconnected

    added = relink_notes(repo, SimilarityReconciler())
    assert added >= 2  # a→b and b→a
    pairs = {(edge.source_id, edge.target_id) for edge in repo.edges()}
    assert ("a", "b") in pairs and ("b", "a") in pairs
    assert not any(source == target for source, target in pairs)  # no self-links


def test_relink_is_idempotent() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("a", "Alpha"), (1.0, 0.0))
    repo.add_note(
        _note("b", "Beta"), (0.6, 0.8)
    )  # RELATED band → an edge to add, then re-run is a no-op
    first = relink_notes(repo, SimilarityReconciler())
    assert first > 0
    before = {(edge.source_id, edge.target_id) for edge in repo.edges()}
    second = relink_notes(repo, SimilarityReconciler())  # re-run
    assert second == 0  # nothing new
    assert {(edge.source_id, edge.target_id) for edge in repo.edges()} == before  # no duplicates


def test_relink_leaves_dissimilar_notes_unconnected() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("a", "Alpha"), (1.0, 0.0))
    repo.add_note(_note("b", "Beta"), (0.0, 1.0))  # orthogonal → cosine 0, below the link threshold
    added = relink_notes(repo, SimilarityReconciler())
    assert added == 0
    assert repo.edges() == ()
