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
    # `note` is the derived current note (ADR-0008/PR-C): edited fields + derived status, so
    # graph.json agrees with Plan.md and the re-rendered note files (all regenerated per projection).
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


def to_graph(repo: NoteRepository) -> dict[str, object]:
    # `_grandplan` is a sentinel so a regenerated graph.json is recognised as ours (and only ours
    # is ever overwritten — see core.project); external consumers simply ignore the extra key.
    notes = repo.current_notes()
    live_ids = {note.id for note in notes}  # exclude edges touching a deleted/tombstoned note
    return {
        "_grandplan": True,
        "nodes": [_node(note) for note in notes],
        "edges": [
            _edge(edge)
            for edge in repo.edges()
            if edge.source_id in live_ids and edge.target_id in live_ids
        ],
    }


def export_graph(repo: NoteRepository, path: Path) -> Path:
    path.write_text(json.dumps(to_graph(repo), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
