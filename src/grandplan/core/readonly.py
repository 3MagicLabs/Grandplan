"""Read-only proxies over the write ports (SPEC-READONLY §3.1).

`gui --read-only` promises that a process cannot modify the vault. Hiding the Approve button and
skipping the hotkey listener would *implement* that promise today and quietly break it the first time
someone adds a write path — the guarantee would decay with every feature.

So the promise is made structurally instead: the repository and the vault writer are replaced with
proxies that **raise on every mutator and delegate every reader**. Anything that tries to write fails
loudly wherever it is, including code that does not exist yet. The button-hiding still happens (a
raise is a bad way to tell a user "not in this mode"), but it is the ergonomics, not the mechanism.

Deliberately not a `Protocol` implementation by inheritance: these wrap whatever concrete repo/writer
the app built, so a port method added later that this file does not know about is not silently
forwarded — `__getattr__` is not defined, so it raises `AttributeError` and the test suite says so.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from grandplan.core.models import (
    Edge,
    Note,
    NoteEdit,
    NoteEvent,
    NoteStatus,
    Original,
)
from grandplan.core.ports import NoteRepository, VaultWriter
from grandplan.core.resources import Resource


class VaultIsReadOnly(RuntimeError):
    """A write was attempted in read-only mode (SPEC-READONLY §3.2) — loud, never silent."""

    def __init__(self, operation: str) -> None:
        super().__init__(
            f"{operation} refused: this vault is open read-only (`--read-only`). Nothing has been "
            "written. Restart without --read-only to make changes."
        )


class ReadOnlyRepository:
    """A `NoteRepository` whose six mutators raise and whose readers pass straight through."""

    def __init__(self, inner: NoteRepository) -> None:
        self._inner = inner

    # --- writes: every mutator on the port, sealed -----------------------------------------------

    def add_note(self, note: Note, embedding: tuple[float, ...]) -> None:
        raise VaultIsReadOnly("adding a note")

    def add_edge(self, edge: Edge) -> None:
        raise VaultIsReadOnly("linking notes")

    def set_status(
        self, note_id: str, status: NoteStatus, *, at: str | None = None, detail: str = ""
    ) -> None:
        raise VaultIsReadOnly("changing a note's status")

    def record_edit(self, note_id: str, edit: NoteEdit, *, at: str | None = None) -> None:
        raise VaultIsReadOnly("editing a note")

    def add_resource(self, note_id: str, resource: Resource, *, at: str | None = None) -> None:
        raise VaultIsReadOnly("attaching a resource")

    def delete_note(self, note_id: str, *, at: str | None = None) -> None:
        raise VaultIsReadOnly("deleting a note")

    # --- reads: unchanged (SPEC-READONLY §3.4 — a degraded read-only mode would not get used) -----

    def get_note(self, note_id: str) -> Note | None:
        return self._inner.get_note(note_id)

    def embedding_of(self, note_id: str) -> tuple[float, ...] | None:
        return self._inner.embedding_of(note_id)

    def notes(self) -> tuple[Note, ...]:
        return self._inner.notes()

    def edges(self) -> tuple[Edge, ...]:
        return self._inner.edges()

    def status_of(self, note_id: str) -> NoteStatus | None:
        return self._inner.status_of(note_id)

    def current_note(self, note_id: str) -> Note | None:
        return self._inner.current_note(note_id)

    def current_notes(self) -> tuple[Note, ...]:
        return self._inner.current_notes()

    def resources_of(self, note_id: str) -> tuple[Resource, ...]:
        return self._inner.resources_of(note_id)

    def history_of(self, note_id: str) -> tuple[NoteEvent, ...]:
        return self._inner.history_of(note_id)

    def events(self) -> tuple[NoteEvent, ...]:
        return self._inner.events()

    def most_similar(
        self, embedding: tuple[float, ...], *, limit: int = 5, threshold: float = 0.0
    ) -> tuple[tuple[Note, float], ...]:
        return self._inner.most_similar(embedding, limit=limit, threshold=threshold)


class ReadOnlyVaultWriter:
    """A `VaultWriter` that refuses to put anything on disk."""

    def write(
        self,
        note: Note,
        original: Original,
        links: tuple[Edge, ...],
        *,
        targets: Mapping[str, Note] | None = None,
        status: NoteStatus | None = None,
        history: tuple[NoteEvent, ...] = (),
        stems: Mapping[str, str] | None = None,
        backlinks: tuple[Edge, ...] = (),
        sources: Mapping[str, Note] | None = None,
    ) -> Path:
        raise VaultIsReadOnly("writing a note file")


def seal(repo: NoteRepository, vault: VaultWriter) -> tuple[NoteRepository, VaultWriter]:
    """The read-only pair for a repo/writer — the one place `--read-only` swaps the ports."""
    return ReadOnlyRepository(repo), ReadOnlyVaultWriter()
