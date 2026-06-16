"""JSON graph projection — nodes + typed edges from the note repository.

A portable, dependency-free export (the "reusable by other software" requirement, US-9). The
same node/edge model is the source for the document, the graph view, and the plan (SPEC §11).
"""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.core.models import Edge, Note
from grandplan.core.ports import NoteRepository


def _node(note: Note) -> dict[str, object]:
    return {
        "id": note.id,
        "title": note.title,
        "type": note.type.value,
        "status": note.status.value,
        "horizon": note.horizon.value,
        "tags": list(note.tags),
        "original_id": note.original_id,
    }


def _edge(edge: Edge) -> dict[str, object]:
    return {"source": edge.source_id, "target": edge.target_id, "kind": edge.kind.value}


def to_graph(repo: NoteRepository) -> dict[str, list[dict[str, object]]]:
    return {
        "nodes": [_node(note) for note in repo.notes()],
        "edges": [_edge(edge) for edge in repo.edges()],
    }


def export_graph(repo: NoteRepository, path: Path) -> Path:
    path.write_text(json.dumps(to_graph(repo), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
