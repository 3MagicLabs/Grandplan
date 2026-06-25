"""Tests for core.retrieval — chunk-aware (hybrid) similarity over chunk embeddings."""

from __future__ import annotations

import pytest

from grandplan.core.embed import HashingEmbedder
from grandplan.core.retrieval import ChunkIndex, blend, max_pool

_EMB = HashingEmbedder(dims=128)


def test_max_pool_is_best_chunk_similarity() -> None:
    q = _EMB.embed("alpha beta")
    near = _EMB.embed("alpha beta")
    far = _EMB.embed("totally unrelated words here")
    assert max_pool(q, (far, near)) == pytest.approx(1.0)  # picks the matching chunk
    assert max_pool(q, ()) == 0.0  # no chunks → no signal


def test_chunk_index_recalls_a_note_via_a_single_matching_passage() -> None:
    # noteA buries an exact match in one paragraph among unrelated text; noteB is unrelated.
    query = "quarterly revenue forecast model"
    noteA = (
        "random opening thoughts about lunch.\n\n" + query + "\n\nclosing unrelated chatter here."
    )
    noteB = "a note about gardening tomatoes and watering schedules in spring."
    idx = ChunkIndex(_EMB)
    idx.add("A", noteA)
    idx.add("B", noteB)

    ranked = idx.most_similar(_EMB.embed(query), limit=5)
    assert ranked[0][0] == "A"  # the buried-passage note is recalled first
    assert ranked[0][1] > (ranked[1][1] if len(ranked) > 1 else 0.0)
    # Chunk-level beats note-level: the whole-note embedding of A is diluted by the other paragraphs.
    note_level = _EMB.embed(noteA)
    assert ranked[0][1] > sum(a * b for a, b in zip(_EMB.embed(query), note_level))


def test_chunk_index_respects_threshold_and_limit() -> None:
    idx = ChunkIndex(_EMB)
    idx.add("A", "apples and oranges")
    idx.add("B", "spaceships orbiting distant moons")
    ranked = idx.most_similar(_EMB.embed("apples and oranges"), limit=1, threshold=0.5)
    assert len(ranked) == 1 and ranked[0][0] == "A"
    assert idx.most_similar(_EMB.embed("apples"), threshold=0.99) == ()  # nothing clears the bar


def test_empty_note_adds_no_chunks() -> None:
    idx = ChunkIndex(_EMB)
    idx.add("A", "   \n\n  ")
    assert idx.most_similar(_EMB.embed("anything")) == ()


def test_blend_combines_note_and_chunk_scores() -> None:
    note_scores = {"A": 0.2, "B": 0.9}
    chunk_scores = {"A": 1.0, "B": 0.1}
    ranked = dict(blend(note_scores, chunk_scores, alpha=0.5))
    assert ranked["A"] == pytest.approx(0.6)  # 0.5*0.2 + 0.5*1.0
    assert ranked["B"] == pytest.approx(0.5)  # 0.5*0.9 + 0.5*0.1
    # alpha=1 → note-only; alpha=0 → chunk-only
    assert dict(blend(note_scores, chunk_scores, alpha=1.0))["B"] == pytest.approx(0.9)
    assert dict(blend(note_scores, chunk_scores, alpha=0.0))["A"] == pytest.approx(1.0)


def test_blend_rejects_bad_alpha() -> None:
    with pytest.raises(ValueError):
        blend({}, {}, alpha=1.5)
