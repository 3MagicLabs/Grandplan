"""Tests for the SimilarityReconciler (linking + duplicate detection)."""

from __future__ import annotations

import pytest

from grandplan.core.models import Note, NoteType
from grandplan.core.reconcile import Relationship, SimilarityReconciler
from grandplan.core.repository import InMemoryNoteRepository


def _note(note_id: str) -> Note:
    return Note(id=note_id, original_id=f"o{note_id}", title=note_id, body="b", type=NoteType.IDEA)


def _repo() -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("dup"), (1.0, 0.0, 0.0))  # score 1.0 -> duplicate
    repo.add_note(_note("rel"), (0.6, 0.8, 0.0))  # score 0.6 -> related
    repo.add_note(_note("far"), (0.0, 1.0, 0.0))  # score 0.0 -> below link threshold
    return repo


def test_classifies_duplicate_related_and_excludes_far() -> None:
    proposal = SimilarityReconciler().reconcile((1.0, 0.0, 0.0), _repo())
    by_id = {c.note.id: c.relationship for c in proposal.candidates}
    assert by_id["dup"] is Relationship.DUPLICATE
    assert by_id["rel"] is Relationship.RELATED
    assert "far" not in by_id
    assert proposal.is_probable_duplicate
    assert [n.id for n in proposal.related_notes] == ["rel"]


def test_invalid_thresholds_raise() -> None:
    with pytest.raises(ValueError, match="threshold"):
        SimilarityReconciler(link_threshold=0.9, duplicate_threshold=0.3)
