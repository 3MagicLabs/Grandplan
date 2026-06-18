"""JsonlNoteRepository — an append-only, rehydrating NoteRepository (the note index).

The GUI needs the index to survive restarts so a new capture links against the **whole** vault
history, not just the current session (SPEC US-5). This adapter mirrors `JsonlOriginalStore`:
each note (with its embedding) and each edge is one line of UTF-8 JSON, append-only and
idempotent on identical content; a fresh instance rehydrates the full in-memory index from disk.

Similarity search and querying delegate to an in-memory `InMemoryNoteRepository`, so the core's
ranking logic stays in one place (a SQLite/sqlite-vec adapter can replace this later, per QAS-5).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from grandplan.core.models import (
    Edge,
    EdgeKind,
    Horizon,
    Note,
    NoteEdit,
    NoteEvent,
    NoteStatus,
    NoteType,
    apply_edit,
)
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.resources import Resource, ResourceKind

logger = logging.getLogger(__name__)


class JsonlNoteRepository:
    """Persistent NoteRepository: in-memory index backed by an append-only JSON-Lines file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._mem = InMemoryNoteRepository()
        if path.exists():
            self._load()

    def _load(self) -> None:
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                record = line.rstrip("\n")
                if not record:
                    continue
                self._apply(json.loads(record))

    def _apply(self, record: Any) -> None:
        kind = record.get("kind")
        if kind == "note":
            note = _note_from_dict(record["note"])
            embedding = tuple(float(v) for v in record["embedding"])
            self._mem.add_note(note, embedding)
        elif kind == "edge":
            self._mem.add_edge(_edge_from_dict(record["edge"]))
        elif kind == "status":
            # Replay the status event onto the in-memory log; last line wins (ADR-0008).
            self._mem.set_status(
                str(record["note_id"]), NoteStatus(str(record["status"])), at=record.get("at")
            )
        elif kind == "edit":
            # Replay a field edit (PR-C); derived state folds edits in append order over the note.
            self._mem.record_edit(
                str(record["note_id"]), _edit_from_dict(record["edit"]), at=record.get("at")
            )
        else:
            # An unknown/corrupt record kind would otherwise be silently dropped — surface it so a
            # forward-incompatible or damaged line can't disappear without a trace.
            logger.warning("skipping index record with unknown kind %r", kind)

    def _append(self, record: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def add_note(self, note: Note, embedding: tuple[float, ...]) -> None:
        if self._mem.get_note(note.id) is not None:
            return  # append-only + idempotent on identical content
        self._mem.add_note(note, embedding)
        self._append({"kind": "note", "note": _note_to_dict(note), "embedding": list(embedding)})

    def add_edge(self, edge: Edge) -> None:
        if edge in self._mem.edges():
            return
        self._mem.add_edge(edge)
        self._append({"kind": "edge", "edge": _edge_to_dict(edge)})

    def set_status(self, note_id: str, status: NoteStatus, *, at: str | None = None) -> None:
        if self._mem.status_of(note_id) is status:
            return  # no state change → no event (append-only + idempotent, like add_note/add_edge)
        self._mem.set_status(note_id, status, at=at)
        record: dict[str, object] = {"kind": "status", "note_id": note_id, "status": status.value}
        if at is not None:
            record["at"] = at
        self._append(record)

    def status_of(self, note_id: str) -> NoteStatus | None:
        return self._mem.status_of(note_id)

    def record_edit(self, note_id: str, edit: NoteEdit, *, at: str | None = None) -> None:
        current = self._mem.current_note(note_id)
        if current is None or apply_edit(current, edit) == current:
            return  # unknown note or no-op → no event (idempotent + orphan-guarded)
        self._mem.record_edit(note_id, edit, at=at)
        record: dict[str, object] = {
            "kind": "edit",
            "note_id": note_id,
            "edit": _edit_to_dict(edit),
        }
        if at is not None:
            record["at"] = at
        self._append(record)

    def current_note(self, note_id: str) -> Note | None:
        return self._mem.current_note(note_id)

    def current_notes(self) -> tuple[Note, ...]:
        return self._mem.current_notes()

    def history_of(self, note_id: str) -> tuple[NoteEvent, ...]:
        return self._mem.history_of(note_id)

    def events(self) -> tuple[NoteEvent, ...]:
        return self._mem.events()

    def get_note(self, note_id: str) -> Note | None:
        return self._mem.get_note(note_id)

    def notes(self) -> tuple[Note, ...]:
        return self._mem.notes()

    def edges(self) -> tuple[Edge, ...]:
        return self._mem.edges()

    def most_similar(
        self, embedding: tuple[float, ...], *, limit: int = 5, threshold: float = 0.0
    ) -> tuple[tuple[Note, float], ...]:
        return self._mem.most_similar(embedding, limit=limit, threshold=threshold)


def _note_to_dict(note: Note) -> dict[str, object]:
    return {
        "id": note.id,
        "original_id": note.original_id,
        "title": note.title,
        "body": note.body,
        "type": note.type.value,
        "status": note.status.value,
        "horizon": note.horizon.value,
        "tags": list(note.tags),
        "contexts": list(note.contexts),
        "due": note.due,
        "collections": list(note.collections),
        "resources": [_resource_to_dict(resource) for resource in note.resources],
    }


def _note_from_dict(data: Any) -> Note:
    return Note(
        id=str(data["id"]),
        original_id=str(data["original_id"]),
        title=str(data["title"]),
        body=str(data["body"]),
        type=NoteType(str(data["type"])),
        status=NoteStatus(str(data["status"])),
        horizon=Horizon(str(data["horizon"])),
        tags=tuple(str(t) for t in data.get("tags", [])),
        contexts=tuple(str(c) for c in data.get("contexts", [])),
        due=None if data.get("due") is None else str(data["due"]),
        collections=tuple(str(c) for c in data.get("collections", [])),
        # Absent in pre-PR-D index records → () (backward compatible).
        resources=tuple(_resource_from_dict(r) for r in data.get("resources", [])),
    )


def _resource_to_dict(resource: Resource) -> dict[str, object]:
    return {"kind": resource.kind.value, "ref": resource.ref, "label": resource.label}


def _resource_from_dict(data: Any) -> Resource:
    return Resource(
        kind=ResourceKind(str(data["kind"])),
        ref=str(data["ref"]),
        label=str(data.get("label", "")),
    )


def _edit_to_dict(edit: NoteEdit) -> dict[str, object]:
    # Only the fields the edit actually sets are persisted (None = "unchanged", never serialized).
    out: dict[str, object] = {}
    if edit.title is not None:
        out["title"] = edit.title
    if edit.body is not None:
        out["body"] = edit.body
    if edit.tags is not None:
        out["tags"] = list(edit.tags)
    if edit.due is not None:
        out["due"] = edit.due
    return out


def _edit_from_dict(data: Any) -> NoteEdit:
    tags = data.get("tags")
    return NoteEdit(
        title=None if data.get("title") is None else str(data["title"]),
        body=None if data.get("body") is None else str(data["body"]),
        tags=None if tags is None else tuple(str(tag) for tag in tags),
        due=None if data.get("due") is None else str(data["due"]),
    )


def _edge_to_dict(edge: Edge) -> dict[str, object]:
    return {"source_id": edge.source_id, "target_id": edge.target_id, "kind": edge.kind.value}


def _edge_from_dict(data: Any) -> Edge:
    return Edge(
        source_id=str(data["source_id"]),
        target_id=str(data["target_id"]),
        kind=EdgeKind(str(data["kind"])),
    )
