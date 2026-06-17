"""Tests for relationship classification + the SimilarityReconciler (US-10 / #12)."""

from __future__ import annotations

import pytest

from grandplan.core.models import EdgeKind, Note, NoteType, ProposedNote
from grandplan.core.reconcile import (
    RELATIONSHIP_EDGE_KIND,
    Relationship,
    SimilarityClassifier,
    SimilarityReconciler,
)
from grandplan.core.repository import InMemoryNoteRepository


def _note(note_id: str) -> Note:
    return Note(id=note_id, original_id=f"o{note_id}", title=note_id, body="b", type=NoteType.IDEA)


def _proposed(title: str = "new") -> ProposedNote:
    return ProposedNote(original_id="o", title=title, body="b", type=NoteType.IDEA)


def _repo() -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("dup"), (1.0, 0.0, 0.0))  # score 1.0 -> duplicate
    repo.add_note(_note("rel"), (0.6, 0.8, 0.0))  # score 0.6 -> related
    repo.add_note(_note("far"), (0.0, 1.0, 0.0))  # score 0.0 -> below link threshold
    return repo


class _FixedClassifier:
    """Test Strategy: classify each candidate by id, regardless of similarity."""

    def __init__(self, mapping: dict[str, Relationship]) -> None:
        self._mapping = mapping

    def classify(self, new: ProposedNote, candidate: Note, score: float) -> Relationship:
        return self._mapping[candidate.id]


def test_baseline_classifies_duplicate_related_and_excludes_far() -> None:
    proposal = SimilarityReconciler().reconcile(_proposed(), (1.0, 0.0, 0.0), _repo())
    by_id = {c.note.id: c.relationship for c in proposal.candidates}
    assert by_id["dup"] is Relationship.DUPLICATE
    assert by_id["rel"] is Relationship.RELATED
    assert "far" not in by_id
    assert proposal.is_probable_duplicate
    assert [n.id for n in proposal.related_notes] == ["rel"]


def test_invalid_thresholds_raise() -> None:
    with pytest.raises(ValueError, match="threshold"):
        SimilarityReconciler(link_threshold=0.9, duplicate_threshold=0.3)


def test_duplicate_threshold_with_custom_classifier_is_rejected() -> None:
    # duplicate_threshold only configures the default classifier; pairing it with a custom one
    # would silently do nothing, so it's an explicit error rather than a silent no-op.
    with pytest.raises(ValueError, match="duplicate_threshold is unused"):
        SimilarityReconciler(duplicate_threshold=0.5, classifier=SimilarityClassifier())


def test_similarity_classifier_bands() -> None:
    clf = SimilarityClassifier(duplicate_threshold=0.9)
    assert clf.classify(_proposed(), _note("x"), 0.95) is Relationship.DUPLICATE
    assert clf.classify(_proposed(), _note("x"), 0.50) is Relationship.RELATED


def test_links_map_relationships_to_typed_edges_excluding_duplicates() -> None:
    classifier = _FixedClassifier({"dup": Relationship.DUPLICATE, "rel": Relationship.SUPERSEDES})
    proposal = SimilarityReconciler(classifier=classifier).reconcile(
        _proposed(), (1.0, 0.0, 0.0), _repo()
    )
    links = {note.id: kind for note, kind in proposal.links()}
    assert links == {"rel": EdgeKind.SUPERSEDES}  # duplicate -> no auto edge (it's the merge path)


def test_requires_review_and_contradicts_edge_when_a_candidate_conflicts() -> None:
    classifier = _FixedClassifier({"dup": Relationship.RELATED, "rel": Relationship.CONTRADICTS})
    proposal = SimilarityReconciler(classifier=classifier).reconcile(
        _proposed(), (1.0, 0.0, 0.0), _repo()
    )
    assert proposal.requires_review  # a contradiction must route the new note to needs-review
    # the conflicting note is kept and gets a contradicts edge (never auto-resolved, US-10)
    assert ("rel", EdgeKind.CONTRADICTS) in [(n.id, k) for n, k in proposal.links()]


def test_builds_on_relationship_maps_to_builds_on_edge() -> None:
    classifier = _FixedClassifier({"dup": Relationship.BUILDS_ON, "rel": Relationship.RELATED})
    proposal = SimilarityReconciler(classifier=classifier).reconcile(
        _proposed(), (1.0, 0.0, 0.0), _repo()
    )
    links = {note.id: kind for note, kind in proposal.links()}
    assert links["dup"] is EdgeKind.BUILDS_ON
    assert links["rel"] is EdgeKind.RELATES


def test_edge_kind_mapping_covers_every_relationship() -> None:
    for relationship in Relationship:
        assert relationship in RELATIONSHIP_EDGE_KIND  # exhaustive: no relationship left unmapped
    assert RELATIONSHIP_EDGE_KIND[Relationship.DUPLICATE] is None
    assert RELATIONSHIP_EDGE_KIND[Relationship.CONTRADICTS] is EdgeKind.CONTRADICTS
