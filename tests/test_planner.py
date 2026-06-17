"""Tests for the Planner projection (now / blocked / order / hierarchy / cycle)."""

from __future__ import annotations

from pathlib import Path

from grandplan.core.models import Edge, EdgeKind, Horizon, Note, NoteStatus, NoteType
from grandplan.core.planner import build_plan, render_plan, write_plan
from grandplan.core.repository import InMemoryNoteRepository


def _note(
    nid: str,
    *,
    note_type: NoteType = NoteType.TASK,
    status: NoteStatus = NoteStatus.INBOX,
    horizon: Horizon = Horizon.ACTION,
    title: str | None = None,
) -> Note:
    return Note(
        id=nid,
        original_id=f"o{nid}",
        title=title or nid,
        body="b",
        type=note_type,
        status=status,
        horizon=horizon,
    )


def _repo(notes: list[Note], edges: list[Edge]) -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    for note in notes:
        repo.add_note(note, (1.0,))
    for edge in edges:
        repo.add_edge(edge)
    return repo


def test_now_and_blocked_split() -> None:
    repo = _repo([_note("A"), _note("B")], [Edge("B", "A", EdgeKind.DEPENDS_ON)])
    plan = build_plan(repo)
    assert [n.id for n in plan.now] == ["A"]
    assert [item.note.id for item in plan.blocked] == ["B"]
    assert plan.blocked[0].blocked_by[0].id == "A"


def test_completing_dependency_unblocks() -> None:
    repo = _repo(
        [_note("A", status=NoteStatus.DONE), _note("B")],
        [Edge("B", "A", EdgeKind.DEPENDS_ON)],
    )
    assert [n.id for n in build_plan(repo).now] == ["B"]


def test_non_task_and_done_excluded_from_now() -> None:
    repo = _repo(
        [_note("I", note_type=NoteType.IDEA), _note("D", status=NoteStatus.DONE)],
        [],
    )
    assert build_plan(repo).now == ()


def test_ordered_respects_dependencies() -> None:
    repo = _repo([_note("A"), _note("B")], [Edge("B", "A", EdgeKind.DEPENDS_ON)])
    ids = [n.id for n in build_plan(repo).ordered]
    assert ids.index("A") < ids.index("B")


def test_cycle_detected_and_excluded() -> None:
    repo = _repo(
        [_note("A"), _note("B")],
        [Edge("A", "B", EdgeKind.DEPENDS_ON), Edge("B", "A", EdgeKind.DEPENDS_ON)],
    )
    plan = build_plan(repo)
    assert {n.id for n in plan.cycle} == {"A", "B"}
    assert plan.now == ()


def test_hierarchy_nests_part_of() -> None:
    goal = _note("G", note_type=NoteType.GOAL, horizon=Horizon.GOAL)
    proj = _note("P", note_type=NoteType.PROJECT, horizon=Horizon.PROJECT)
    act = _note("A")
    repo = _repo(
        [goal, proj, act],
        [Edge("P", "G", EdgeKind.PART_OF), Edge("A", "P", EdgeKind.PART_OF)],
    )
    plan = build_plan(repo)
    assert plan.root_ids == ("G",)
    assert plan.child_ids["G"] == ("P",)
    assert plan.child_ids["P"] == ("A",)


def test_render_contains_sections_and_checkbox() -> None:
    md = render_plan(build_plan(_repo([_note("t1", title="Do the thing")], [])))
    assert "# Plan" in md
    assert "## Now" in md
    assert "- [ ] Do the thing" in md
    assert "## By goal / project" in md


def test_render_includes_mermaid_diagram_with_dependency_edge() -> None:
    repo = _repo(
        [_note("A", title="First"), _note("B", title="Second")],
        [Edge("B", "A", EdgeKind.DEPENDS_ON)],
    )
    md = render_plan(build_plan(repo))
    assert "```mermaid" in md
    assert "graph TD" in md
    assert 'nA["First"]' in md
    assert "nA --> nB" in md  # prerequisite A points to dependent B


def test_mermaid_label_is_sanitized() -> None:
    repo = _repo([_note("A", title='Quote " and [brackets]')], [])
    md = render_plan(build_plan(repo))
    # Characters that would break a Mermaid node label must be neutralized.
    assert '"Quote " and' not in md
    assert "[brackets]" not in md.split("graph TD", 1)[1]


def test_write_plan_creates_file(tmp_path: Path) -> None:
    out = write_plan(_repo([_note("t1", title="X")], []), tmp_path / "Plan.md")
    assert out.exists()
    assert "# Plan" in out.read_text(encoding="utf-8")
