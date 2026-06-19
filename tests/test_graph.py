"""Tests for the JSON graph projection."""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.core.graph import export_graph, to_graph
from grandplan.core.models import Edge, EdgeKind, Note, NoteEdit, NoteStatus, NoteType
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


def test_us9_export_is_a_portable_open_format(tmp_path: Path) -> None:
    # US-9: data in open formats with no proprietary lock-in — a third party needs only the
    # stdlib json module + the documented node/typed-edge schema to consume the whole graph.
    out = export_graph(_repo(), tmp_path / "graph.json")
    data = json.loads(out.read_text(encoding="utf-8"))  # plain JSON, no custom loader
    assert {"nodes", "edges"} <= set(data)  # subset: forward-compatible if fields are added
    for node in data["nodes"]:
        assert {"id", "title", "type", "status", "horizon", "tags", "original_id"} <= set(node)
        assert isinstance(node["type"], str)  # plain string enum value, not a proprietary object
    for edge in data["edges"]:
        assert {"source", "target", "kind"} <= set(edge)
        assert isinstance(edge["kind"], str)  # typed edge as an open string


def test_node_status_reflects_derived_status() -> None:
    # PR-A: graph.json is a projection of the event log, so a node shows the derived status.
    repo = _repo()  # node "b" is a TASK with creation status INBOX
    repo.set_status("b", NoteStatus.DONE)
    statuses = {node["id"]: node["status"] for node in to_graph(repo)["nodes"]}
    assert statuses["b"] == "done"


def test_node_reflects_edited_fields() -> None:
    # PR-C: graph.json renders the derived current note, so an edited title/tags show up.
    repo = _repo()
    repo.record_edit("a", NoteEdit(title="A (renamed)", tags=("topic",)))
    node = next(n for n in to_graph(repo)["nodes"] if n["id"] == "a")
    assert node["title"] == "A (renamed)" and node["tags"] == ["topic"]


def test_graph_excludes_deleted_notes_and_their_dangling_edges() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(
        Note(id="a", original_id="oa", title="A", body="b", type=NoteType.TASK), (1.0, 0.0)
    )
    repo.add_note(
        Note(id="b", original_id="ob", title="B", body="b", type=NoteType.TASK), (0.0, 1.0)
    )
    repo.add_edge(Edge("a", "b", EdgeKind.RELATES))
    repo.delete_note("b")

    graph = to_graph(repo)
    assert [node["id"] for node in graph["nodes"]] == ["a"]  # deleted note gone
    assert graph["edges"] == []  # the edge to the deleted note is dropped, not left dangling
