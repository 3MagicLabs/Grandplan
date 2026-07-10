"""Tests for the SentenceTransformerEmbedder adapter (normalisation; encode injected)."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

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


def test_offline_env_set_only_when_the_model_is_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # QAS-1 offline: once the model is in the local HF cache, load it with ZERO network — flip
    # HF_HUB_OFFLINE on. A fresh (uncached) machine must stay online for the one-time download.
    from grandplan.adapters.st_embedder import _prefer_offline_when_cached

    monkeypatch.setenv("HF_HOME", str(tmp_path))
    for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        monkeypatch.delenv(var, raising=False)

    # Nothing cached yet → do NOT force offline (the first download needs the network).
    assert _prefer_offline_when_cached("all-MiniLM-L6-v2") is False
    assert "HF_HUB_OFFLINE" not in os.environ

    # Simulate the model having been downloaded, then re-check → offline is forced on.
    (tmp_path / "hub" / "models--sentence-transformers--all-MiniLM-L6-v2").mkdir(parents=True)
    assert _prefer_offline_when_cached("all-MiniLM-L6-v2") is True
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"


def test_offline_never_overrides_an_explicit_user_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from grandplan.adapters.st_embedder import _prefer_offline_when_cached

    monkeypatch.setenv("HF_HOME", str(tmp_path))
    (tmp_path / "hub" / "models--sentence-transformers--all-MiniLM-L6-v2").mkdir(parents=True)
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")  # user deliberately allows the network
    _prefer_offline_when_cached("all-MiniLM-L6-v2")
    assert os.environ["HF_HUB_OFFLINE"] == "0"  # setdefault never clobbers it
