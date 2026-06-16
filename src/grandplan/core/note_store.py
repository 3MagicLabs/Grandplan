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
from pathlib import Path
from typing import Any

from grandplan.core.models import Edge, EdgeKind, Horizon, Note, NoteStatus, NoteType
from grandplan.core.repository import InMemoryNoteRepository


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
        if record.get("kind") == "note":
            note = _note_from_dict(record["note"])
            embedding = tuple(float(v) for v in record["embedding"])
            self._mem.add_note(note, embedding)
        elif record.get("kind") == "edge":
            self._mem.add_edge(_edge_from_dict(record["edge"]))

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
    )


def _edge_to_dict(edge: Edge) -> dict[str, object]:
    return {"source_id": edge.source_id, "target_id": edge.target_id, "kind": edge.kind.value}


def _edge_from_dict(data: Any) -> Edge:
    return Edge(
        source_id=str(data["source_id"]),
        target_id=str(data["target_id"]),
        kind=EdgeKind(str(data["kind"])),
    )
