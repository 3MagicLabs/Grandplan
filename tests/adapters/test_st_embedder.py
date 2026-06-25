"""Tests for the SentenceTransformerEmbedder adapter (normalisation; encode injected)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from grandplan.adapters.st_embedder import SentenceTransformerEmbedder


def test_normalises_to_unit_vector() -> None:
    def encode(text: str) -> Sequence[float]:
        return [3.0, 4.0]

    vec = SentenceTransformerEmbedder(encode=encode).embed("x")
    assert vec == pytest.approx((0.6, 0.8))


def test_zero_vector_stays_zero() -> None:
    def encode(text: str) -> Sequence[float]:
        return [0.0, 0.0, 0.0]

    assert SentenceTransformerEmbedder(encode=encode).embed("x") == (0.0, 0.0, 0.0)


def test_encode_receives_the_text() -> None:
    seen: list[str] = []

    def encode(text: str) -> Sequence[float]:
        seen.append(text)
        return [1.0]

    SentenceTransformerEmbedder(encode=encode).embed("hello")
    assert seen == ["hello"]
