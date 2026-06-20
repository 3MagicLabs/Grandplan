"""Tests for the Planner projection (now / blocked / order / hierarchy / cycle)."""

from __future__ import annotations

from pathlib import Path

from grandplan.core.models import Edge, EdgeKind, Horizon, Note, NoteEdit, NoteStatus, NoteType
from grandplan.core.planner import build_plan, render_masterplan, render_plan, write_plan
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


def test_plan_uses_edited_title_and_lists_what_moved(tmp_path: Path) -> None:
    # PR-C: the plan renders derived (edited) titles and a "What moved" digest of recent events.
    repo = _repo([_note("A", title="draft the spec")], [])
    repo.record_edit("A", NoteEdit(title="finalize the spec"), at="2026-06-17T10:00:00Z")
    repo.set_status("A", NoteStatus.DONE, at="2026-06-17T11:00:00Z")

    plan = build_plan(repo)
    text = render_plan(plan)
    assert "finalize the spec" in text and "draft the spec" not in text  # derived title
    assert "## What moved" in text
    # Most-recent first: the DONE status event leads, then the edit.
    assert plan.moved[0].startswith("finalize the spec: status → done")
    assert any("edit: title → finalize the spec" in line for line in plan.moved)


def test_masterplan_groups_roots_by_horizon_top_down() -> None:
    repo = _repo(
        [
            _note("G", note_type=NoteType.GOAL, horizon=Horizon.GOAL, title="World peace"),
            _note("P", note_type=NoteType.PROJECT, horizon=Horizon.PROJECT, title="Launch the app"),
            _note("A", note_type=NoteType.TASK, horizon=Horizon.ACTION, title="Write the tests"),
        ],
        [],
    )
    md = render_masterplan(build_plan(repo))
    assert md.index("## Goals") < md.index("## Projects") < md.index("## Actions & ideas")
    assert "World peace" in md and "Launch the app" in md and "Write the tests" in md


def test_entity_notes_are_excluded_from_masterplan_roots() -> None:
    # `entity` nodes are cross-cutting referents (joined by `involves`), not planning roots.
    repo = _repo(
        [
            _note("A", note_type=NoteType.TASK, title="ship the feature"),
            _note("E", note_type=NoteType.ENTITY, title="Sarah Chen"),
        ],
        [Edge("A", "E", EdgeKind.INVOLVES)],
    )
    plan = build_plan(repo)
    assert "E" not in plan.root_ids and "A" in plan.root_ids
    assert "Sarah Chen" not in render_masterplan(plan)


def test_no_events_means_no_what_moved_section() -> None:
    repo = _repo([_note("A")], [])
    assert build_plan(repo).moved == ()
    assert "## What moved" not in render_plan(build_plan(repo))


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


def test_mermaid_includes_related_connection() -> None:
    repo = _repo(
        [_note("A", title="First"), _note("B", title="Second")],
        [Edge("B", "A", EdgeKind.RELATES)],
    )
    md = render_plan(build_plan(repo))
    # Semantic links from capture appear in the diagram so the map reflects real connections.
    assert "nB -.->|related| nA" in md


def test_superseded_note_excluded_from_now() -> None:
    # B supersedes A → A is stale and must drop out of the actionable plan (US-10), without
    # mutating A's stored status (the edge is authoritative; ADR-0007).
    repo = _repo([_note("A"), _note("B")], [Edge("B", "A", EdgeKind.SUPERSEDES)])
    plan = build_plan(repo)
    assert [n.id for n in plan.now] == ["B"]
    assert all(item.note.id != "A" for item in plan.blocked)


def test_contradiction_surfaces_in_needs_review_section() -> None:
    repo = _repo(
        [_note("X", title="Use Postgres"), _note("Y", title="Use MongoDB")],
        [Edge("X", "Y", EdgeKind.CONTRADICTS)],
    )
    plan = build_plan(repo)
    assert {n.id for n in plan.needs_review} == {"X", "Y"}
    md = render_plan(plan)
    assert "## ⚠ Needs review" in md
    assert "contradiction: Use Postgres ⟷ Use MongoDB" in md


def test_needs_review_status_note_is_flagged_and_not_actionable() -> None:
    repo = _repo([_note("Q", status=NoteStatus.NEEDS_REVIEW, title="Unresolved")], [])
    plan = build_plan(repo)
    assert [n.id for n in plan.needs_review] == ["Q"]
    assert plan.now == ()  # a needs-review note must NOT also appear as actionable "now"
    assert "## ⚠ Needs review" in render_plan(plan)


def test_clean_plan_has_no_needs_review_section() -> None:
    md = render_plan(build_plan(_repo([_note("t1", title="Solo")], [])))
    assert "Needs review" not in md  # absent when there's nothing to resolve


def test_write_plan_creates_file(tmp_path: Path) -> None:
    out = write_plan(_repo([_note("t1", title="X")], []), tmp_path / "Plan.md")
    assert out.exists()
    assert "# Plan" in out.read_text(encoding="utf-8")


def test_status_event_done_unblocks_dependents_and_leaves_now() -> None:
    # PR-A: the planner reads the *derived* status. A status event marking A done must unblock its
    # dependent B and drop A from "Now" — same effect as a creation-time done, but event-sourced.
    repo = _repo([_note("A"), _note("B")], [Edge("B", "A", EdgeKind.DEPENDS_ON)])
    assert [n.id for n in build_plan(repo).now] == ["A"]  # before the event
    repo.set_status("A", NoteStatus.DONE)
    plan = build_plan(repo)
    assert [n.id for n in plan.now] == ["B"]
    assert plan.status_by_id["A"] is NoteStatus.DONE


def test_status_event_needs_review_flags_and_removes_from_now() -> None:
    repo = _repo([_note("A")], [])
    repo.set_status("A", NoteStatus.NEEDS_REVIEW)
    plan = build_plan(repo)
    assert [n.id for n in plan.needs_review] == ["A"]
    assert plan.now == ()  # a derived needs-review note is not actionable


def test_render_tree_checkbox_reflects_derived_done() -> None:
    repo = _repo([_note("A", title="Ship it")], [])
    repo.set_status("A", NoteStatus.DONE)
    assert "- [x] Ship it" in render_plan(build_plan(repo))
