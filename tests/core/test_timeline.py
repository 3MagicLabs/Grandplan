"""Tests for the feasible-timeline projection (dependency DAG + due dates)."""

from __future__ import annotations

from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Edge, EdgeKind, Note, NoteType
from grandplan.core.planner import build_timeline, render_timeline
from grandplan.core.repository import InMemoryNoteRepository


def _task(nid: str, title: str, due: str | None = None) -> Note:
    return Note(id=nid, original_id=f"o{nid}", title=title, body="b", type=NoteType.TASK, due=due)


def _two_step_repo() -> InMemoryNoteRepository:
    repo, emb = InMemoryNoteRepository(), HashingEmbedder()
    repo.add_note(_task("a", "Design API", "2026-07-01"), emb.embed("design"))
    repo.add_note(_task("b", "Build API", "2026-07-10"), emb.embed("build"))
    repo.add_edge(Edge("b", "a", EdgeKind.DEPENDS_ON))  # build depends on design
    return repo


def test_timeline_splits_ready_and_waiting() -> None:
    timeline = build_timeline(_two_step_repo())
    assert [n.id for n in timeline.ready] == ["a"]  # design is unblocked
    assert [i.note.id for i in timeline.waiting] == ["b"]  # build waits on design
    assert timeline.waiting[0].blocked_by[0].title == "Design API"
    assert [n.id for n in timeline.scheduled] == ["a", "b"]  # both dated, in date order
    assert timeline.conflicts == ()


def test_waiting_on_edge_is_treated_as_a_dependency() -> None:
    repo, emb = InMemoryNoteRepository(), HashingEmbedder()
    repo.add_note(_task("a", "External approval"), emb.embed("approval"))
    repo.add_note(_task("b", "Ship release"), emb.embed("ship"))
    repo.add_edge(Edge("b", "a", EdgeKind.WAITING_ON))
    timeline = build_timeline(repo)
    assert [i.note.id for i in timeline.waiting] == ["b"]  # ship waits on the approval


def test_blocks_edge_makes_the_target_wait() -> None:
    repo, emb = InMemoryNoteRepository(), HashingEmbedder()
    repo.add_note(_task("a", "Foundations"), emb.embed("foundations"))
    repo.add_note(_task("b", "Walls"), emb.embed("walls"))
    repo.add_edge(Edge("a", "b", EdgeKind.BLOCKS))  # foundations blocks walls ⇒ walls waits
    timeline = build_timeline(repo)
    assert [n.id for n in timeline.ready] == ["a"]
    assert [i.note.id for i in timeline.waiting] == ["b"]


def test_timeline_flags_due_before_prerequisite_conflict() -> None:
    repo, emb = InMemoryNoteRepository(), HashingEmbedder()
    repo.add_note(_task("a", "Prerequisite", "2026-08-01"), emb.embed("prereq"))
    repo.add_note(_task("b", "Dependent", "2026-07-01"), emb.embed("dependent"))
    repo.add_edge(Edge("b", "a", EdgeKind.DEPENDS_ON))  # b due before its prerequisite a
    timeline = build_timeline(repo)
    assert any("due before its prerequisite" in c for c in timeline.conflicts)


def test_render_timeline_has_sections() -> None:
    out = render_timeline(build_timeline(_two_step_repo()))
    assert "# Timeline" in out
    assert "## Ready now" in out and "## Waiting" in out and "## Scheduled by date" in out
    assert "- [ ] Design API  (due: 2026-07-01)" in out
    assert "Build API" in out and "waiting on: Design API" in out
