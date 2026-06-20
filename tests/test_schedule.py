"""Tests for scheduling analytics — critical path + parallel batches over the dependency DAG."""

from __future__ import annotations

from grandplan.core.models import Edge, EdgeKind, Note, NoteStatus, NoteType
from grandplan.core.planner import build_plan
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.schedule import critical_path, parallel_batches


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
