"""Ports (interfaces) the platform-agnostic core depends on (ADR-0003).

Adapters implement these; the core never imports concrete Windows/LLM/IO code directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from grandplan.core.models import Edge, Note, Original, ProposedNote


class Organizer(Protocol):
    """Turn a verbatim Original into a proposed structured note (offline)."""

    def organize(self, original: Original) -> ProposedNote: ...


class Embedder(Protocol):
    """Map text to a unit vector for semantic similarity (offline)."""

    def embed(self, text: str) -> tuple[float, ...]: ...


class NoteRepository(Protocol):
    """Persist notes, their embeddings, and typed edges; query by similarity."""

    def add_note(self, note: Note, embedding: tuple[float, ...]) -> None: ...

    def get_note(self, note_id: str) -> Note | None: ...

    def notes(self) -> tuple[Note, ...]: ...

    def add_edge(self, edge: Edge) -> None: ...

    def edges(self) -> tuple[Edge, ...]: ...

    def most_similar(
        self, embedding: tuple[float, ...], *, limit: int = 5, threshold: float = 0.0
    ) -> tuple[tuple[Note, float], ...]: ...


class VaultWriter(Protocol):
    """Write an approved note (with its links) into a vault; return the file path."""

    def write(self, note: Note, original: Original, links: tuple[Edge, ...]) -> Path: ...
