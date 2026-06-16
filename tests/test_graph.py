"""Tests for the JSON graph projection."""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.core.graph import export_graph, to_graph
from grandplan.core.models import Edge, EdgeKind, Note, NoteType
from grandplan.core.repository import InMemoryNoteRepository


def _repo() -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    repo.add_note(Note(id="a", original_id="oa", title="A", body="x", type=NoteType.IDEA), (1.0,))
    repo.add_note(Note(id="b", original_id="ob", title="B", body="y", type=NoteType.TASK), (0.0,))
    repo.add_edge(Edge("a", "b", EdgeKind.RELATES))
    return repo


def test_to_graph_has_nodes_and_edges() -> None:
    graph = to_graph(_repo())
    assert {node["id"] for node in graph["nodes"]} == {"a", "b"}
    assert graph["edges"] == [{"source": "a", "target": "b", "kind": "relates"}]


def test_export_graph_writes_valid_json(tmp_path: Path) -> None:
    out = export_graph(_repo(), tmp_path / "graph.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["nodes"]) == 2
    assert data["edges"][0]["kind"] == "relates"
