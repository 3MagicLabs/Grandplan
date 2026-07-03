"""InMemoryNoteRepository — append-only in-memory NoteRepository with cosine similarity.

The default implementation of the `NoteRepository` port. Notes are append-only (never
mutated/overwritten); similarity is a dot product over unit embeddings. A SQLite + sqlite-vec
adapter can later replace it without core changes.
"""

from __future__ import annotations

from dataclasses import replace

from grandplan.core.models import Edge, Note, NoteEdit, NoteEvent, NoteStatus, apply_edit
from grandplan.core.resources import Resource, ResourceKind


class InMemoryNoteRepository:
    """In-memory notes + embeddings + edges + an event log, with similarity search."""

    def __init__(self) -> None:
        self._notes: dict[str, Note] = {}
        self._embeddings: dict[str, tuple[float, ...]] = {}
        self._edges: list[Edge] = []
        # Global append-order log of status/edit events (ADR-0008). Current state is *derived* by
        # replaying it; the stored notes are never mutated. Absent events => creation state.
        self._events: list[NoteEvent] = []
        # Derived tombstone set, maintained alongside the log (ADR-0009 cheap win): `_is_deleted`
        # used to re-scan the WHOLE event log, and `most_similar` calls it once per note — an
        # O(N·E) inner loop on every similarity query. The set is pure derivation (delete events
        # only ever enter through `delete_note`), so replay/rebuild semantics are unchanged.
        self._tombstones: set[str] = set()

    def add_note(self, note: Note, embedding: tuple[float, ...]) -> None:
        if note.id in self._notes:
            return  # append-only + idempotent on identical content
        self._notes[note.id] = note
        self._embeddings[note.id] = embedding

    def _is_deleted(self, note_id: str) -> bool:
        return note_id in self._tombstones

    def delete_note(self, note_id: str, *, at: str | None = None) -> None:
        if note_id not in self._notes or self._is_deleted(note_id):
            return  # unknown or already tombstoned → idempotent + orphan-guarded
        self._events.append(NoteEvent(note_id=note_id, kind="deleted", at=at))
        self._tombstones.add(note_id)

    def get_note(self, note_id: str) -> Note | None:
        if self._is_deleted(note_id):
            return None  # tombstoned → gone from every derived view
        return self._notes.get(note_id)

    def embedding_of(self, note_id: str) -> tuple[float, ...] | None:
        """The stored embedding (creation-time, immutable) — lets an external similarity index
        (ADR-0009: sqlite-vec adapter) backfill/rebuild without re-embedding. None when unknown."""
        return self._embeddings.get(note_id)

    def notes(self) -> tuple[Note, ...]:
        return tuple(self._notes.values())

    def add_edge(self, edge: Edge) -> None:
        if edge not in self._edges:
            self._edges.append(edge)

    def edges(self) -> tuple[Edge, ...]:
        return tuple(self._edges)

    def set_status(
        self, note_id: str, status: NoteStatus, *, at: str | None = None, detail: str = ""
    ) -> None:
        if self.status_of(note_id) is status:
            return  # no change → no event (idempotent, append-only)
        self._events.append(
            NoteEvent(note_id=note_id, kind="status", at=at, status=status, detail=detail)
        )

    def record_edit(self, note_id: str, edit: NoteEdit, *, at: str | None = None) -> None:
        current = self.current_note(note_id)
        if current is None or apply_edit(current, edit) == current:
            return  # unknown note or no-op → no event (idempotent + orphan-guarded)
        self._events.append(NoteEvent(note_id=note_id, kind="edit", at=at, edit=edit))

    def add_resource(self, note_id: str, resource: Resource, *, at: str | None = None) -> None:
        if self._notes.get(note_id) is None:
            return  # unknown note → no orphan event (PR-E)
        if (resource.kind, resource.ref) in {(r.kind, r.ref) for r in self.resources_of(note_id)}:
            return  # already attached → idempotent
        self._events.append(NoteEvent(note_id=note_id, kind="resource", at=at, resource=resource))

    def resources_of(self, note_id: str) -> tuple[Resource, ...]:
        """Derived resources: the note's creation-time resources (PR-D) + attached ones (PR-E),
        deduped by (kind, ref), order-stable."""
        note = self._notes.get(note_id)
        if note is None:
            return ()
        out: list[Resource] = []
        seen: set[tuple[ResourceKind, str]] = set()
        attached = (
            event.resource
            for event in self._events
            if event.note_id == note_id and event.kind == "resource" and event.resource is not None
        )
        for resource in (*note.resources, *attached):
            key = (resource.kind, resource.ref)
            if key not in seen:
                seen.add(key)
                out.append(resource)
        return tuple(out)

    def status_of(self, note_id: str) -> NoteStatus | None:
        latest: NoteStatus | None = None
        for event in self._events:
            if event.note_id == note_id and event.kind == "status":
                latest = event.status
        if latest is not None:
            return latest
        note = self._notes.get(note_id)
        return note.status if note is not None else None

    def current_note(self, note_id: str) -> Note | None:
        # Derivation replays the event log (O(events)); `current_notes` does this per note. Fine at
        # personal scale; memoise a note_id→(status, edits) index here if the log ever grows large.
        if self._is_deleted(note_id):
            return None  # tombstoned → excluded from the plan/graph/timeline projections
        note = self._notes.get(note_id)
        if note is None:
            return None
        for event in self._events:
            if event.note_id == note_id and event.kind == "edit" and event.edit is not None:
                note = apply_edit(note, event.edit)
        status = self.status_of(note_id)
        if status is not None and status is not note.status:
            note = replace(note, status=status)
        resources = self.resources_of(note_id)  # creation + attached (PR-E)
        if resources != note.resources:
            note = replace(note, resources=resources)
        return note

    def current_notes(self) -> tuple[Note, ...]:
        derived = [self.current_note(note_id) for note_id in self._notes]
        return tuple(note for note in derived if note is not None)

    def history_of(self, note_id: str) -> tuple[NoteEvent, ...]:
        return tuple(event for event in self._events if event.note_id == note_id)

    def events(self) -> tuple[NoteEvent, ...]:
        return tuple(self._events)

    def most_similar(
        self, embedding: tuple[float, ...], *, limit: int = 5, threshold: float = 0.0
    ) -> tuple[tuple[Note, float], ...]:
        scored: list[tuple[Note, float]] = []
        for note_id, other in self._embeddings.items():
            if self._is_deleted(note_id):
                continue  # never link a new capture to a deleted note
            score = _dot(embedding, other)
            if score >= threshold:
                scored.append((self._notes[note_id], score))
        scored.sort(key=lambda item: (-item[1], item[0].id))
        return tuple(scored[:limit])


def _dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=False)))
