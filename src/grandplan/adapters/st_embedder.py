"""SentenceTransformerEmbedder — a local sentence-embedding adapter (offline).

Drop-in for the `Embedder` port using a local sentence-transformers model (e.g.
all-MiniLM-L6-v2). The model runs on-device; nothing leaves the machine. Vectors are
L2-normalised so cosine similarity is a dot product (matching the core's expectations).

The encode step is injected, so the normalisation logic is unit-tested here; the real model
load needs the optional dependency and is integration-tested on the user's machine
(`pip install grandplan[embeddings]`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

_DEFAULT_MODEL = "all-MiniLM-L6-v2"
EncodeFn = Callable[[str], Sequence[float]]


def _lazy_encode(model_name: str) -> EncodeFn:  # pragma: no cover - needs the model + dependency
    model: Any = None

    def encode(text: str) -> Sequence[float]:
        nonlocal model
        if model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    f"sentence-transformers unavailable ({exc}); `pip install grandplan[embeddings]`"
                ) from exc
            model = SentenceTransformer(model_name)
        return [float(value) for value in model.encode(text)]

    return encode


class SentenceTransformerEmbedder:
    """Embedder backed by a local sentence-transformers model; emits unit vectors."""

    def __init__(self, *, model_name: str = _DEFAULT_MODEL, encode: EncodeFn | None = None) -> None:
        self._encode: EncodeFn = encode or _lazy_encode(model_name)

    def embed(self, text: str) -> tuple[float, ...]:
        return _normalize(self._encode(text))


def _normalize(vector: Sequence[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if norm == 0.0:
        return tuple(float(value) for value in vector)
    return tuple(float(value) / norm for value in vector)
