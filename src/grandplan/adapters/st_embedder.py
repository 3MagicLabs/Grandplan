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
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

_DEFAULT_MODEL = "all-MiniLM-L6-v2"
EncodeFn = Callable[[str], Sequence[float]]


def _quiet_hf_console() -> None:
    """Silence the HF/transformers console noise (a tqdm 'Batches' bar per embed call + the
    unauthenticated-Hub warning) that buried grandplan's own output. setdefault: an explicit
    user setting always wins. The model itself is unaffected — this is presentation only."""
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")


def _hf_hub_cache_dir() -> Path:
    """Where huggingface_hub caches models (HF_HOME/hub, or the platform default)."""
    for env in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if os.environ.get(env):
            return Path(os.environ[env])
    home = os.environ.get("HF_HOME")
    base = Path(home) if home else Path.home() / ".cache" / "huggingface"
    return base / "hub"


def _prefer_offline_when_cached(model_name: str) -> bool:
    """Grandplan is offline-only (QAS-1): once the embedding model is in the local HF cache, load it
    with ZERO network. Otherwise sentence-transformers phones huggingface.co on EVERY load just to
    revalidate the cache — real egress that breaks the offline guarantee and adds seconds of latency.
    We flip HF_HUB_OFFLINE on only when the model is ALREADY cached, so a fresh machine can still do
    the ONE-time download. setdefault → an explicit user env setting always wins. Must run before the
    sentence_transformers import (huggingface_hub reads these at import time). Returns whether cached.
    """
    leaf = model_name.rsplit("/", 1)[
        -1
    ]  # "sentence-transformers/all-MiniLM-L6-v2" → "all-MiniLM-L6-v2"
    hub = _hf_hub_cache_dir()
    cached = hub.is_dir() and any(leaf in entry.name for entry in hub.iterdir())
    if cached:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    return cached


def _lazy_encode(model_name: str) -> EncodeFn:  # pragma: no cover - needs the model + dependency
    model: Any = None

    def encode(text: str) -> Sequence[float]:
        nonlocal model
        if model is None:
            # Must precede the import — huggingface_hub reads these env vars at import time.
            _quiet_hf_console()
            _prefer_offline_when_cached(model_name)  # no network once the model is cached
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    f"sentence-transformers unavailable ({exc}); `pip install grandplan[embeddings]`"
                ) from exc
            model = SentenceTransformer(model_name)
        return [float(value) for value in model.encode(text, show_progress_bar=False)]

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
