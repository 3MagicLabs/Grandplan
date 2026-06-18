"""Ports (interfaces) the platform-agnostic core depends on (ADR-0003).

Adapters implement these; the core never imports concrete Windows/LLM/IO code directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from grandplan.core.models import (
    Edge,
    Note,
    NoteEdit,
    NoteEvent,
    NoteStatus,
    Original,
    ProposedNote,
)
from grandplan.core.resources import Resource


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

    def set_status(self, note_id: str, status: NoteStatus, *, at: str | None = None) -> None:
        """Record a note's new current status as an event (append-only; never mutates the note).

        `at` is an optional caller-supplied timestamp (the capture's `created`) for history; no
        hidden clock. Idempotent: recording the current derived status records nothing.
        """
        ...

    def status_of(self, note_id: str) -> NoteStatus | None:
        """Derived current status: latest status event, else creation status, else None if unknown."""
        ...

    def record_edit(self, note_id: str, edit: NoteEdit, *, at: str | None = None) -> None:
        """Record a field edit as an event (PR-C); the stored note is never mutated, its id stable.

        No-op if the note is unknown, the edit is empty, or it changes nothing (idempotent).
        """
        ...

    def current_note(self, note_id: str) -> Note | None:
        """The derived current note: stored note + replayed edits + derived status (None if unknown)."""
        ...

    def current_notes(self) -> tuple[Note, ...]:
        """`current_note` for every stored note — the derived view the projections render."""
        ...

    def add_resource(self, note_id: str, resource: Resource, *, at: str | None = None) -> None:
        """Attach a resource to a note as an event (PR-E); idempotent + orphan-guarded."""
        ...

    def resources_of(self, note_id: str) -> tuple[Resource, ...]:
        """Derived resources: the note's creation-time resources + attached ones (PR-D/PR-E)."""
        ...

    def history_of(self, note_id: str) -> tuple[NoteEvent, ...]:
        """This note's events (status + edit + resource) in order — its "git log"."""
        ...

    def events(self) -> tuple[NoteEvent, ...]:
        """All events across the repository, in global append order (drives the 'what moved' digest)."""
        ...

    def most_similar(
        self, embedding: tuple[float, ...], *, limit: int = 5, threshold: float = 0.0
    ) -> tuple[tuple[Note, float], ...]: ...


class VaultWriter(Protocol):
    """Write an approved note (with its links) into a vault; return the file path.

    `targets` maps each link's target_id to the target Note so links can render as resolvable
    `[[filename|title]]` wikilinks (SPEC US-5: no broken links).
    """

    def write(
        self,
        note: Note,
        original: Original,
        links: tuple[Edge, ...],
        *,
        targets: Mapping[str, Note] | None = None,
        status: NoteStatus | None = None,
        history: tuple[NoteEvent, ...] = (),
    ) -> Path: ...


class Capturer(Protocol):
    """Capture the user's current text selection from any app (None if nothing selectable)."""

    def capture(self) -> str | None: ...
