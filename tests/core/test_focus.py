"""Tests for the focus views — the deterministic `/focus` render + the bounded chat prompt block.

Both are pure functions of a `Plan` and never call a model: the whole point of `/focus` is that the
priority view survives an Ollama outage (SPEC-ACT §3 "Degradation").
"""

from __future__ import annotations

from grandplan.core.focus import _NOW_CAP, _PATH_CAP, plan_context_block, render_focus
from grandplan.core.models import Edge, EdgeKind, Horizon, Note, NoteStatus, NoteType
from grandplan.core.planner import build_plan
from grandplan.core.repository import InMemoryNoteRepository


def _task(nid: str, title: str | None = None, body: str = "b") -> Note:
    return Note(id=nid, original_id=f"o{nid}", title=title or nid, body=body, type=NoteType.TASK)


def _goal(nid: str, title: str) -> Note:
    return Note(
        id=nid,
        original_id=f"o{nid}",
        title=title,
        body="b",
        type=NoteType.GOAL,
        horizon=Horizon.GOAL,
    )


def _repo(notes: list[Note], edges: list[Edge]) -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    for note in notes:
        repo.add_note(note, (1.0,))
    for edge in edges:
        repo.add_edge(edge)
    return repo


def _chain(n: int) -> InMemoryNoteRepository:
    """A single dependency chain t0 → t1 → … → t(n-1) (each depends on the previous)."""
    notes = [_task(f"t{i}", f"Task {i}") for i in range(n)]
    edges = [Edge(f"t{i}", f"t{i - 1}", EdgeKind.DEPENDS_ON) for i in range(1, n)]
    return _repo(notes, edges)


# --- render_focus -------------------------------------------------------------------------------


def test_render_focus_shows_the_bottleneck_chain_in_execution_order() -> None:
    # The critical path is what to protect; it must read prerequisite-first so the top line is the
    # thing to actually start on.
    text = render_focus(build_plan(_chain(3)))
    assert "Task 0" in text and "Task 2" in text
    assert text.index("Task 0") < text.index("Task 1") < text.index("Task 2")


def test_render_focus_on_an_empty_vault_says_so_rather_than_rendering_empty_sections() -> None:
    text = render_focus(build_plan(InMemoryNoteRepository()))
    assert "nothing open" in text.lower()


def test_render_focus_reports_a_cycle_instead_of_a_silently_empty_path() -> None:
    # A ↔ B: critical_path() returns () because neither note resolves a depth. Rendering that as an
    # empty bottleneck would read as "no work left" — the opposite of the truth.
    repo = _repo(
        [_task("A", "Alpha"), _task("B", "Beta")],
        [Edge("A", "B", EdgeKind.DEPENDS_ON), Edge("B", "A", EdgeKind.DEPENDS_ON)],
    )
    text = render_focus(build_plan(repo)).lower()
    assert "cycle" in text


def test_render_focus_includes_progress_rollup() -> None:
    repo = _repo(
        [_goal("G", "Ship v1"), _task("T1"), _task("T2")],
        [Edge("T1", "G", EdgeKind.PART_OF), Edge("T2", "G", EdgeKind.PART_OF)],
    )
    repo.set_status("T1", NoteStatus.DONE, at="2026")
    text = render_focus(build_plan(repo))
    assert "Ship v1" in text
    assert "50%" in text


# --- plan_context_block -------------------------------------------------------------------------


def test_plan_context_block_is_empty_when_nothing_is_open() -> None:
    # An empty block is worse than none: it invites the model to fill the silence. Omit it.
    assert plan_context_block(build_plan(InMemoryNoteRepository())) == ""


def test_plan_context_block_carries_the_critical_path_and_now() -> None:
    block = plan_context_block(build_plan(_chain(3)))
    assert "Task 0" in block
    assert "critical path" in block.lower()


def test_plan_context_block_marks_itself_authoritative_for_priority() -> None:
    # The retrieved notes ground content; this block grounds sequence. The model must be told which
    # is which, or it will answer "what's most important" from whatever six notes happened to match.
    block = plan_context_block(build_plan(_chain(2))).lower()
    assert "priority" in block or "sequence" in block


def test_plan_context_block_caps_the_path_and_marks_the_truncation() -> None:
    # num_ctx is finite: an unbounded chain would crowd out the retrieved notes. Truncation must be
    # visible, or the model reads a partial chain as the whole chain.
    block = plan_context_block(build_plan(_chain(_PATH_CAP + 5)))
    assert f"Task {_PATH_CAP - 1}" in block  # the cap'th item is present
    assert f"Task {_PATH_CAP}" not in block  # the one past it is not
    assert "more" in block  # ... and the drop is announced


def test_plan_context_block_caps_the_now_list() -> None:
    # 20 independent tasks are all actionable now; only _NOW_CAP may reach the prompt.
    repo = _repo([_task(f"n{i}", f"Now {i}") for i in range(_NOW_CAP + 6)], [])
    block = plan_context_block(build_plan(repo))
    now_line = next(
        line for line in block.splitlines() if line.lower().startswith("actionable now")
    )
    assert now_line.count("[") == _NOW_CAP
    assert "more" in now_line


def test_plan_context_block_never_includes_note_bodies() -> None:
    # Titles + ids only. Bodies are what the retrieval section is for; duplicating them here would
    # double-spend the context window on the same notes.
    repo = _repo([_task("t0", "Findable title", body="UNIQUE_BODY_SENTINEL")], [])
    block = plan_context_block(build_plan(repo))
    assert "Findable title" in block
    assert "UNIQUE_BODY_SENTINEL" not in block
