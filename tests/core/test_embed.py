"""Tests for the dependency-free, deterministic HashingEmbedder."""

from __future__ import annotations

import math

import pytest

from grandplan.core.embed import HashingEmbedder


def _dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_nonempty_text_is_unit_vector() -> None:
    vec = HashingEmbedder().embed("machine learning and neural networks")
    assert math.isclose(math.sqrt(sum(v * v for v in vec)), 1.0, abs_tol=1e-9)


def test_empty_text_is_zero_vector() -> None:
    vec = HashingEmbedder(dims=32).embed("   ")
    assert len(vec) == 32
    assert all(v == 0.0 for v in vec)


def test_related_text_is_more_similar_than_unrelated() -> None:
    embedder = HashingEmbedder()
    base = embedder.embed("machine learning models and neural networks")
    related = embedder.embed("neural networks for machine learning")
    unrelated = embedder.embed("grocery shopping list with bananas and milk")
    assert _dot(base, related) > _dot(base, unrelated)


def test_invalid_dims_raise() -> None:
    with pytest.raises(ValueError, match="positive"):
        HashingEmbedder(dims=0)
