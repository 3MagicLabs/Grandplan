"""InMemoryNoteRepository — append-only in-memory NoteRepository with cosine similarity.

The default implementation of the `NoteRepository` port. Notes are append-only (never
mutated/overwritten); similarity is a dot product over unit embeddings. A SQLite + sqlite-vec
adapter can later replace it without core changes.
"""

from __future__ import annotations

from grandplan.core.models import Edge, Note, NoteStatus


class InMemoryNoteRepository:
    """In-memory notes + embeddings + edges, with similarity search."""

    def __init__(self) -> None:
        self._notes: dict[str, Note] = {}
        self._embeddings: dict[str, tuple[float, ...]] = {}
        self._edges: list[Edge] = []
        # note_id -> latest status from a status event (ADR-0008). Absent => no event yet, so the
        # derived status falls back to the note's creation status. The note is never mutated.
        self._statuses: dict[str, NoteStatus] = {}

    def add_note(self, note: Note, embedding: tuple[float, ...]) -> None:
        if note.id in self._notes:
            return  # append-only + idempotent on identical content
        self._notes[note.id] = note
        self._embeddings[note.id] = embedding

    def get_note(self, note_id: str) -> Note | None:
        return self._notes.get(note_id)

    def notes(self) -> tuple[Note, ...]:
        return tuple(self._notes.values())

    def add_edge(self, edge: Edge) -> None:
        if edge not in self._edges:
            self._edges.append(edge)

    def edges(self) -> tuple[Edge, ...]:
        return tuple(self._edges)

    def set_status(self, note_id: str, status: NoteStatus) -> None:
        self._statuses[note_id] = status  # last-write-wins: the most recent event is current

    def status_of(self, note_id: str) -> NoteStatus | None:
        if note_id in self._statuses:
            return self._statuses[note_id]
        note = self._notes.get(note_id)
        return note.status if note is not None else None

    def most_similar(
        self, embedding: tuple[float, ...], *, limit: int = 5, threshold: float = 0.0
    ) -> tuple[tuple[Note, float], ...]:
        scored: list[tuple[Note, float]] = []
        for note_id, other in self._embeddings.items():
            score = _dot(embedding, other)
            if score >= threshold:
                scored.append((self._notes[note_id], score))
        scored.sort(key=lambda item: (-item[1], item[0].id))
        return tuple(scored[:limit])


def _dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=False)))
