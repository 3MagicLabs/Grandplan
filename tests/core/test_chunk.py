"""Tests for core.chunk — paragraph-aware, bounded text chunking + chunk embedding."""

from __future__ import annotations

import pytest

from grandplan.core.chunk import chunk_text, embed_chunks
from grandplan.core.embed import HashingEmbedder


def test_short_text_is_a_single_chunk() -> None:
    assert chunk_text("one small thought") == ("one small thought",)


def test_blank_or_whitespace_text_yields_no_chunks() -> None:
    assert chunk_text("   \n\n  ") == ()
    assert chunk_text("") == ()


def test_paragraphs_split_into_one_chunk_each() -> None:
    text = "First paragraph here.\n\nSecond paragraph here.\n\nThird."
    assert chunk_text(text) == ("First paragraph here.", "Second paragraph here.", "Third.")


def test_long_paragraph_is_windowed_within_max_chars_with_overlap() -> None:
    para = "x" * 1000
    chunks = chunk_text(para, max_chars=400, overlap=50)
    assert len(chunks) >= 3
    assert all(len(c) <= 400 for c in chunks)  # every chunk respects the bound
    # Overlap: consecutive windows share characters (stride = max_chars - overlap = 350).
    assert chunks[0][-50:] == chunks[1][:50]
    # Lossless coverage: concatenating with the overlap removed reconstructs the paragraph.
    rebuilt = chunks[0] + "".join(c[50:] for c in chunks[1:])
    assert rebuilt == para


def test_invalid_params_raise() -> None:
    with pytest.raises(ValueError):
        chunk_text("hi", max_chars=0)
    with pytest.raises(ValueError):
        chunk_text("hi", max_chars=100, overlap=100)  # overlap must be < max_chars
    with pytest.raises(ValueError):
        chunk_text("hi", max_chars=100, overlap=-1)


def test_embed_chunks_pairs_each_chunk_with_a_unit_vector() -> None:
    text = "alpha beta gamma.\n\ndelta epsilon zeta."
    embedder = HashingEmbedder(dims=64)
    pairs = embed_chunks(text, embedder)
    assert tuple(chunk for chunk, _ in pairs) == chunk_text(text)
    for _, vec in pairs:
        assert len(vec) == 64
        norm = sum(v * v for v in vec) ** 0.5
        assert abs(norm - 1.0) < 1e-9  # unit vector
