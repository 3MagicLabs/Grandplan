"""Tests for the InMemoryNoteRepository (append-only + similarity search)."""

from __future__ import annotations

from grandplan.core.models import Edge, EdgeKind, Note, NoteType
from grandplan.core.repository import InMemoryNoteRepository


def _note(note_id: str) -> Note:
    return Note(id=note_id, original_id="o", title=note_id, body="b", type=NoteType.IDEA)


def test_add_note_is_append_only_and_idempotent() -> None:
    repo = InMemoryNoteRepository()
    note = _note("n1")
    repo.add_note(note, (1.0, 0.0))
    repo.add_note(note, (0.0, 1.0))  # ignored — append-only
    assert repo.get_note("n1") == note
    assert len(repo.notes()) == 1


def test_add_edge_deduplicates() -> None:
    repo = InMemoryNoteRepository()
    edge = Edge("a", "b", EdgeKind.RELATES)
    repo.add_edge(edge)
    repo.add_edge(edge)
    assert repo.edges() == (edge,)


def test_most_similar_orders_thresholds_and_limits() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("a"), (1.0, 0.0, 0.0))
    repo.add_note(_note("b"), (0.0, 1.0, 0.0))
    repo.add_note(_note("c"), (0.7, 0.7, 0.0))
    query = (1.0, 0.0, 0.0)

    assert [n.id for n, _ in repo.most_similar(query)] == ["a", "c", "b"]
    assert [n.id for n, _ in repo.most_similar(query, threshold=0.5)] == ["a", "c"]
    assert [n.id for n, _ in repo.most_similar(query, limit=1)] == ["a"]
