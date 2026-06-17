"""JSON graph projection — nodes + typed edges from the note repository.

A portable, dependency-free export (the "reusable by other software" requirement, US-9). The
same node/edge model is the source for the document, the graph view, and the plan (SPEC §11).
"""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.core.models import Edge, Note, NoteStatus
from grandplan.core.ports import NoteRepository


def _node(note: Note, status: NoteStatus) -> dict[str, object]:
    # `status` is the derived current status (ADR-0008), so graph.json agrees with Plan.md (both
    # regenerated on every projection). Per-note vault .md frontmatter only reflects derived status
    # on re-render (PR-C); until then a note's .md shows its creation status while these views move.
    return {
        "id": note.id,
        "title": note.title,
        "type": note.type.value,
        "status": status.value,
        "horizon": note.horizon.value,
        "tags": list(note.tags),
        "original_id": note.original_id,
    }


def _edge(edge: Edge) -> dict[str, object]:
    return {"source": edge.source_id, "target": edge.target_id, "kind": edge.kind.value}


def to_graph(repo: NoteRepository) -> dict[str, object]:
    # `_grandplan` is a sentinel so a regenerated graph.json is recognised as ours (and only ours
    # is ever overwritten — see core.project); external consumers simply ignore the extra key.
    return {
        "_grandplan": True,
        "nodes": [_node(note, repo.status_of(note.id) or note.status) for note in repo.notes()],
        "edges": [_edge(edge) for edge in repo.edges()],
    }


def export_graph(repo: NoteRepository, path: Path) -> Path:
    path.write_text(json.dumps(to_graph(repo), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
