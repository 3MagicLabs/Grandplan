"""Chunk-aware (hybrid) retrieval over chunk embeddings (pure, offline).

grandplan's repository scores similarity at *note* level, which dilutes a note whose relevance lives in
a single passage. This module adds chunk-granular scoring: `max_pool` takes the best-matching chunk, a
`ChunkIndex` answers similarity over per-note chunk vectors, and `blend` combines note-level and
chunk-level rankings (the "hybrid" of hybrid retrieval — docs/research/LANDSCAPE.md, Track 1). Pure and
additive: it builds on `chunk.embed_chunks` and the `Embedder` port and changes no storage yet — wiring
it into the repository/reconciler (with persistence) is the next slice.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from grandplan.core.chunk import embed_chunks
from grandplan.core.ports import Embedder

Vector = tuple[float, ...]


def _dot(a: Vector, b: Vector) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=False)))


def max_pool(query: Vector, chunks: Sequence[Vector]) -> float:
    """Best (max) cosine similarity between the query and any chunk; 0.0 when there are no chunks.

    Max-pool (not mean) is the point: a note is relevant if *one* passage matches, even if the rest
    of the note is about something else."""
    return max((_dot(query, chunk) for chunk in chunks), default=0.0)


class ChunkIndex:
    """In-memory `note_id -> chunk vectors` index for chunk-granular similarity (offline, additive).

    Build it from note bodies via `add`; query it with `most_similar`. Independent of the persistent
    repository — a building block the reconciler can adopt without changing the event-sourced store.
    """

    def __init__(self, embedder: Embedder, *, max_chars: int = 512, overlap: int = 64) -> None:
        self._embedder = embedder
        self._max_chars = max_chars
        self._overlap = overlap
        self._chunks: dict[str, tuple[Vector, ...]] = {}

    def add(self, note_id: str, text: str) -> None:
        """Embed `text` into chunk vectors under `note_id` (a note with no chunkable text is skipped)."""
        vectors = tuple(
            vec
            for _, vec in embed_chunks(
                text, self._embedder, max_chars=self._max_chars, overlap=self._overlap
            )
        )
        if vectors:
            self._chunks[note_id] = vectors

    def most_similar(
        self, query: Vector, *, limit: int = 5, threshold: float = 0.0
    ) -> tuple[tuple[str, float], ...]:
        """Notes ranked by their best-matching chunk (max-pool), filtered by `threshold`, top `limit`.

        Ties broken by note_id for determinism."""
        scored = [
            (note_id, score)
            for note_id, chunks in self._chunks.items()
            if (score := max_pool(query, chunks)) >= threshold
        ]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return tuple(scored[:limit])


def blend(
    note_scores: Mapping[str, float], chunk_scores: Mapping[str, float], *, alpha: float = 0.5
) -> tuple[tuple[str, float], ...]:
    """Hybrid rank: `alpha * note_score + (1 - alpha) * chunk_score` over the union of note ids.

    `alpha=1.0` is note-only, `alpha=0.0` is chunk-only. A missing score on either side counts as 0.0.
    Returned highest-first, ties broken by note id."""
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be in [0, 1]")
    ids = set(note_scores) | set(chunk_scores)
    ranked = [
        (
            note_id,
            alpha * note_scores.get(note_id, 0.0) + (1.0 - alpha) * chunk_scores.get(note_id, 0.0),
        )
        for note_id in ids
    ]
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return tuple(ranked)
