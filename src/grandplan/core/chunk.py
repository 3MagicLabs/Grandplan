"""Paragraph-aware, bounded text chunking + chunk-level embedding (pure, offline).

grandplan embeds at *note* level today; chunk-level granularity is the precondition for sharper
linking and for hybrid retrieval that scales to thousands of notes without stuffing whole notes into
the LLM (see docs/research/LANDSCAPE.md, Track 1). This module is pure and dependency-free: it splits
a body into paragraph-bounded chunks (windowing only paragraphs that exceed `max_chars`, with a char
overlap so a match never falls in a seam) and pairs each chunk with a unit vector via the `Embedder`
port. Wiring chunks into the repository/reconciler is a separate, later slice — this layer is additive
and leaves the note-level path untouched.
"""

from __future__ import annotations

import re

from grandplan.core.ports import Embedder

_PARAGRAPH = re.compile(r"\n\s*\n")


def chunk_text(text: str, *, max_chars: int = 512, overlap: int = 64) -> tuple[str, ...]:
    """Split `text` into paragraph-aware chunks, each at most `max_chars` long.

    Paragraphs (blank-line separated) are kept whole when they fit; an over-long paragraph is windowed
    with `overlap` characters shared between consecutive windows (so a phrase split across a boundary
    is still wholly present in one chunk). Concatenating chunk[0] with chunk[i][overlap:] for i>0 of a
    single windowed paragraph reconstructs it exactly (lossless coverage). Returns () for blank input.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if not 0 <= overlap < max_chars:
        raise ValueError("overlap must satisfy 0 <= overlap < max_chars")
    chunks: list[str] = []
    for raw in _PARAGRAPH.split(text.strip()):
        paragraph = raw.strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            chunks.append(paragraph)
        else:
            chunks.extend(_window(paragraph, max_chars, overlap))
    return tuple(chunks)


def _window(text: str, max_chars: int, overlap: int) -> list[str]:
    """Sliding windows of `max_chars` with `overlap` shared chars; stops once a window reaches the end
    (so there is never a redundant fully-overlapped trailing window)."""
    stride = max_chars - overlap
    windows: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = start + max_chars
        windows.append(text[start:end])
        if end >= length:
            break
        start += stride
    return windows


def embed_chunks(
    text: str, embedder: Embedder, *, max_chars: int = 512, overlap: int = 64
) -> tuple[tuple[str, tuple[float, ...]], ...]:
    """Pair each chunk of `text` with its embedding (offline, via the `Embedder` port)."""
    return tuple(
        (chunk, embedder.embed(chunk))
        for chunk in chunk_text(text, max_chars=max_chars, overlap=overlap)
    )
