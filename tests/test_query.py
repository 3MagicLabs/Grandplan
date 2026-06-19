"""Tests for the VaultQuery read facade + the MCP tool registry/dispatch (agent-operable vault)."""

from __future__ import annotations

import pytest

from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import (
    Edge,
    EdgeKind,
    Horizon,
    Note,
    NoteStatus,
    NoteType,
    Original,
    Source,
)
from grandplan.core.query import TOOLS, VaultQuery, dispatch
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore


def _query() -> VaultQuery:
    repo, originals, emb = InMemoryNoteRepository(), InMemoryOriginalStore(), HashingEmbedder()
    originals.add(
        Original(
            id="o1", text="build an offline second brain", source=Source(app="t"), created="2026"
        )
    )
    goal = Note(
        id="g",
        original_id="o1",
        title="build an offline second brain",
        body="the vision",
        type=NoteType.GOAL,
        horizon=Horizon.GOAL,
        tags=("brain",),
    )
    repo.add_note(goal, emb.embed(goal.title))
    originals.add(
        Original(id="o2", text="finish the hotkey capture", source=Source(app="t"), created="2026")
    )
    task = Note(
        id="t",
        original_id="o2",
        title="finish the hotkey capture",
        body="do it",
        type=NoteType.TASK,
        tags=("capture",),
        due="2026-07-01",
    )
    repo.add_note(task, emb.embed(task.title))
    repo.add_edge(Edge("t", "g", EdgeKind.PART_OF))
    repo.set_status("t", NoteStatus.DONE, at="2026")
    return VaultQuery(repo=repo, originals=originals, embedder=emb)


def test_list_notes_returns_briefs() -> None:
    notes = _query().list_notes()
    assert {n["id"] for n in notes} == {"g", "t"}
    task = next(n for n in notes if n["id"] == "t")
    assert task["title"] == "finish the hotkey capture" and task["due"] == "2026-07-01"


def test_get_note_includes_original_links_and_history() -> None:
    note = _query().get_note("t")
    assert note is not None
    assert note["body"] == "do it"
    assert note["original"] == "finish the hotkey capture"  # verbatim, lossless
    assert note["links"] == [
        {"kind": "part_of", "target_id": "g", "target_title": "build an offline second brain"}
    ]
    assert "status → done" in note["history"]


def test_get_note_unknown_returns_none() -> None:
    assert _query().get_note("nope") is None


def test_search_notes_ranks_by_similarity() -> None:
    results = _query().search_notes("hotkey capture", limit=2)
    assert results and results[0]["id"] == "t"  # the closest match first
    assert all("score" in r for r in results)


def test_get_masterplan_nests_task_under_goal() -> None:
    roots = _query().get_masterplan()["roots"]
    assert isinstance(roots, list) and len(roots) == 1
    goal = roots[0]
    assert goal["id"] == "g"
    assert [c["id"] for c in goal["children"]] == ["t"]  # part_of hierarchy


def test_get_timeline_exposes_ready_and_waiting() -> None:
    repo, originals, emb = InMemoryNoteRepository(), InMemoryOriginalStore(), HashingEmbedder()
    a = Note(
        id="a", original_id="oa", title="Design", body="b", type=NoteType.TASK, due="2026-07-01"
    )
    b = Note(id="b", original_id="ob", title="Build", body="b", type=NoteType.TASK)
    repo.add_note(a, emb.embed("design"))
    repo.add_note(b, emb.embed("build"))
    repo.add_edge(Edge("b", "a", EdgeKind.DEPENDS_ON))
    timeline = VaultQuery(repo=repo, originals=originals, embedder=emb).get_timeline()
    assert [n["id"] for n in timeline["ready"]] == ["a"]  # type: ignore[union-attr]
    assert timeline["waiting"][0]["note"]["id"] == "b"  # type: ignore[index]


def test_get_graph_and_doctor() -> None:
    query = _query()
    graph = query.get_graph()
    assert len(graph["nodes"]) == 2 and len(graph["edges"]) == 1
    report = query.doctor()
    assert report["structural_edges"] == 1 and report["note_count"] == 2


def test_dispatch_routes_and_validates_arguments() -> None:
    query = _query()
    assert len(dispatch(query, "list_notes", {})) == 2
    assert dispatch(query, "get_note", {"note_id": "g"})["title"] == "build an offline second brain"  # type: ignore[index]
    with pytest.raises(ValueError, match="missing required string argument"):
        dispatch(query, "get_note", {})
    with pytest.raises(ValueError, match="unknown tool"):
        dispatch(query, "bogus", {})


def test_dispatch_routes_every_advertised_tool() -> None:
    query = _query()
    args = {"get_note": {"note_id": "g"}, "search_notes": {"query": "brain"}}
    for tool in TOOLS:  # every TOOLS entry must route through dispatch without error
        result = dispatch(query, tool.name, args.get(tool.name, {}))
        assert result is not None


def test_tool_registry_is_well_formed() -> None:
    names = [tool.name for tool in TOOLS]
    assert len(names) == len(set(names))  # unique
    for tool in TOOLS:
        assert tool.description and tool.input_schema["type"] == "object"
    # every advertised tool is actually dispatchable
    assert {t.name for t in TOOLS} == {
        "list_notes",
        "get_note",
        "search_notes",
        "get_plan",
        "get_masterplan",
        "get_timeline",
        "get_graph",
        "doctor",
    }
