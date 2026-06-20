"""Tests for scheduling analytics — critical path + parallel batches over the dependency DAG."""

from __future__ import annotations

from grandplan.core.models import Edge, EdgeKind, Horizon, Note, NoteStatus, NoteType
from grandplan.core.planner import build_plan
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.schedule import critical_path, parallel_batches, roll_up_progress


def _task(nid: str, title: str | None = None) -> Note:
    return Note(id=nid, original_id=f"o{nid}", title=title or nid, body="b", type=NoteType.TASK)


def _repo(notes: list[Note], edges: list[Edge]) -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    for note in notes:
        repo.add_note(note, (1.0,))
    for edge in edges:
        repo.add_edge(edge)
    return repo


def test_critical_path_is_the_longest_chain() -> None:
    # A → B → C is the chain (C depends_on B depends_on A); D is independent.
    repo = _repo(
        [_task("A"), _task("B"), _task("C"), _task("D")],
        [Edge("B", "A", EdgeKind.DEPENDS_ON), Edge("C", "B", EdgeKind.DEPENDS_ON)],
    )
    path = [n.id for n in critical_path(build_plan(repo))]
    assert path == ["A", "B", "C"]  # execution order, prerequisite first


def test_critical_path_empty_when_no_tasks() -> None:
    assert critical_path(build_plan(InMemoryNoteRepository())) == ()


def test_critical_path_skips_done_prerequisites() -> None:
    # A is done, so the remaining chain is just B → C.
    repo = _repo(
        [_task("A"), _task("B"), _task("C")],
        [Edge("B", "A", EdgeKind.DEPENDS_ON), Edge("C", "B", EdgeKind.DEPENDS_ON)],
    )
    repo.set_status("A", NoteStatus.DONE, at="2026")
    path = [n.id for n in critical_path(build_plan(repo))]
    assert path == ["B", "C"]


def test_parallel_batches_group_by_depth() -> None:
    # A and D have no prereqs (batch 0); B depends on A, C depends on B (batches 1, 2).
    repo = _repo(
        [_task("A"), _task("B"), _task("C"), _task("D")],
        [Edge("B", "A", EdgeKind.DEPENDS_ON), Edge("C", "B", EdgeKind.DEPENDS_ON)],
    )
    batches = [[n.id for n in batch] for batch in parallel_batches(build_plan(repo))]
    assert batches == [["A", "D"], ["B"], ["C"]]


def test_parallel_batches_empty_when_no_tasks() -> None:
    assert parallel_batches(build_plan(InMemoryNoteRepository())) == ()


def test_blocks_edge_feeds_the_schedule() -> None:
    # "A blocks B" ⇒ B depends on A ⇒ A then B.
    repo = _repo([_task("A"), _task("B")], [Edge("A", "B", EdgeKind.BLOCKS)])
    path = [n.id for n in critical_path(build_plan(repo))]
    assert path == ["A", "B"]


def test_cycle_notes_are_excluded() -> None:
    # A ↔ B is a cycle; neither resolves a depth, so the path is empty (planner reports the cycle).
    repo = _repo(
        [_task("A"), _task("B")],
        [Edge("A", "B", EdgeKind.DEPENDS_ON), Edge("B", "A", EdgeKind.DEPENDS_ON)],
    )
    assert critical_path(build_plan(repo)) == ()
    assert parallel_batches(build_plan(repo)) == ()


def _goal(nid: str, title: str) -> Note:
    return Note(
        id=nid,
        original_id=f"o{nid}",
        title=title,
        body="b",
        type=NoteType.GOAL,
        horizon=Horizon.GOAL,
    )


def test_roll_up_progress_counts_done_descendant_tasks() -> None:
    # Goal G has two tasks under it (T1 done, T2 open) → 50%.
    repo = _repo(
        [_goal("G", "Ship v1"), _task("T1"), _task("T2")],
        [Edge("T1", "G", EdgeKind.PART_OF), Edge("T2", "G", EdgeKind.PART_OF)],
    )
    repo.set_status("T1", NoteStatus.DONE, at="2026")
    rolled = roll_up_progress(build_plan(repo))
    assert len(rolled) == 1
    assert rolled[0].note.id == "G"
    assert (rolled[0].done, rolled[0].total, rolled[0].percent) == (1, 2, 50)


def test_roll_up_progress_is_recursive_through_projects() -> None:
    # G → P (project) → T (task done). The goal rolls up the nested task.
    proj = Note(
        id="P",
        original_id="oP",
        title="Phase 1",
        body="b",
        type=NoteType.PROJECT,
        horizon=Horizon.PROJECT,
    )
    repo = _repo(
        [_goal("G", "Goal"), proj, _task("T")],
        [Edge("P", "G", EdgeKind.PART_OF), Edge("T", "P", EdgeKind.PART_OF)],
    )
    repo.set_status("T", NoteStatus.DONE, at="2026")
    rolled = {p.note.id: p for p in roll_up_progress(build_plan(repo))}
    assert rolled["G"].percent == 100  # the one task under it is done
    assert rolled["P"].percent == 100


def test_roll_up_progress_omits_goals_without_tasks() -> None:
    repo = _repo([_goal("G", "Empty goal")], [])
    assert roll_up_progress(build_plan(repo)) == ()
