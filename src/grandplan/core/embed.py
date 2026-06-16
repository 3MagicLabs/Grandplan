"""HashingEmbedder — a dependency-free, deterministic, fully-offline baseline embedder.

Feature-hashes tokens into a fixed-dimension unit vector, so related texts have high cosine
similarity (= dot product, since vectors are normalised). A real sentence-transformer
embedder can later replace it behind the `Embedder` port without core changes.
"""

from __future__ import annotations

import hashlib
import math
import re

_TOKEN = re.compile(r"[0-9a-z]+")


class HashingEmbedder:
    """Offline feature-hashing embedder producing unit vectors of `dims` dimensions."""

    def __init__(self, dims: int = 256) -> None:
        if dims <= 0:
            raise ValueError("dims must be positive")
        self._dims = dims

    def embed(self, text: str) -> tuple[float, ...]:
        vec = [0.0] * self._dims
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], "big") % self._dims
            vec[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vec))
        if norm == 0.0:
            return tuple(vec)
        return tuple(value / norm for value in vec)
