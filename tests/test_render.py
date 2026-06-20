"""Tests for the Renderer port + MarkdownReportRenderer (knowledge → deliverable, ROADMAP theme E)."""

from __future__ import annotations

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
from grandplan.core.render import MarkdownReportRenderer
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore


def _vault() -> tuple[InMemoryNoteRepository, InMemoryOriginalStore]:
    repo, originals, emb = InMemoryNoteRepository(), InMemoryOriginalStore(), HashingEmbedder()
    originals.add(Original(id="og", text="ship v1", source=Source(app="t"), created="2026"))
    goal = Note(
        id="g",
        original_id="og",
        title="Ship v1",
        body="the goal",
        type=NoteType.GOAL,
        horizon=Horizon.GOAL,
    )
    repo.add_note(goal, emb.embed(goal.title))
    originals.add(Original(id="ot", text="write docs", source=Source(app="t"), created="2026"))
    task = Note(
        id="t",
        original_id="ot",
        title="Write the docs",
        body="do",
        type=NoteType.TASK,
        due="2026-07-01",
    )
    repo.add_note(task, emb.embed(task.title))
    originals.add(Original(id="ob", text="blocked task", source=Source(app="t"), created="2026"))
    blocked = Note(id="b", original_id="ob", title="Release", body="do", type=NoteType.TASK)
    repo.add_note(blocked, emb.embed(blocked.title))
    repo.add_edge(Edge("t", "g", EdgeKind.PART_OF))
    repo.add_edge(Edge("b", "t", EdgeKind.DEPENDS_ON))  # Release waits on docs
    return repo, originals


def test_report_has_title_and_sections() -> None:
    repo, originals = _vault()
    md = MarkdownReportRenderer(title="Status report", created="2026-06-20").render(repo, originals)
    assert md.startswith("# Status report")
    assert "Generated 2026-06-20" in md
    for section in ("## Summary", "## Top priorities", "## By horizon", "## Graph health"):
        assert section in md


def test_report_lists_ready_and_blocked() -> None:
    repo, originals = _vault()
    md = MarkdownReportRenderer().render(repo, originals)
    assert "- [ ] Write the docs" in md  # ready now
    assert "## Blocked" in md
    assert "Release — waiting on: Write the docs" in md


def test_report_shows_scheduled_by_date() -> None:
    repo, originals = _vault()
    md = MarkdownReportRenderer().render(repo, originals)
    assert "## Scheduled (by date)" in md
    assert "2026-07-01 — Write the docs" in md


def test_report_nests_hierarchy_under_horizon() -> None:
    repo, originals = _vault()
    md = MarkdownReportRenderer().render(repo, originals)
    goals_idx = md.index("### Goals")
    assert "- Ship v1" in md
    # the task nests under the goal (deeper indent appears after the Goals heading)
    assert md.index("  - Write the docs", goals_idx) > goals_idx


def test_report_is_deterministic() -> None:
    repo, originals = _vault()
    r = MarkdownReportRenderer(created="2026-06-20")
    assert r.render(repo, originals) == r.render(repo, originals)


def test_report_marks_done_items() -> None:
    repo, originals = _vault()
    repo.set_status("t", NoteStatus.DONE, at="2026")
    md = MarkdownReportRenderer().render(repo, originals)
    assert "Write the docs ✓" in md


def test_report_handles_empty_vault() -> None:
    md = MarkdownReportRenderer().render(InMemoryNoteRepository(), InMemoryOriginalStore())
    assert "**0** notes tracked." in md
    assert "_Nothing actionable and unblocked._" in md
    assert "_No structured hierarchy yet._" in md


def test_report_surfaces_needs_review() -> None:
    repo, originals = _vault()
    repo.set_status("b", NoteStatus.NEEDS_REVIEW, at="2026")
    md = MarkdownReportRenderer().render(repo, originals)
    assert "## Open questions / needs review" in md
    assert "Release" in md


def test_report_shows_critical_path_and_parallel_batches() -> None:
    # A → B chain plus an independent C: a 2-step critical path and a parallelizable first batch.
    repo, originals, emb = InMemoryNoteRepository(), InMemoryOriginalStore(), HashingEmbedder()
    for nid in ("A", "B", "C"):
        originals.add(Original(id=f"o{nid}", text=nid, source=Source(app="t"), created="2026"))
        repo.add_note(
            Note(id=nid, original_id=f"o{nid}", title=f"Task {nid}", body="b", type=NoteType.TASK),
            emb.embed(nid),
        )
    repo.add_edge(Edge("B", "A", EdgeKind.DEPENDS_ON))
    md = MarkdownReportRenderer().render(repo, originals)
    assert "## Critical path (the bottleneck)" in md
    assert "Task A → Task B" in md
    assert "## Parallel batches" in md
    assert "1. Task A, Task C" in md  # both have no prereqs → first batch


def test_report_omits_critical_path_when_no_dependencies() -> None:
    # a single independent task → no chain ≥ 2 and no batch with >1 task
    md = MarkdownReportRenderer().render(*_vault_without_deps())
    assert "## Critical path" not in md
    assert "## Parallel batches" not in md


def _vault_without_deps() -> tuple[InMemoryNoteRepository, InMemoryOriginalStore]:
    repo, originals, emb = InMemoryNoteRepository(), InMemoryOriginalStore(), HashingEmbedder()
    originals.add(Original(id="o", text="solo", source=Source(app="t"), created="2026"))
    repo.add_note(
        Note(id="x", original_id="o", title="Solo task", body="b", type=NoteType.TASK),
        emb.embed("solo"),
    )
    return repo, originals


def test_report_shows_progress_rollup() -> None:
    repo, originals = _vault()  # goal "Ship v1" with one task "Write the docs" under it
    repo.set_status("t", NoteStatus.DONE, at="2026")
    md = MarkdownReportRenderer().render(repo, originals)
    assert "## Progress (goals & projects)" in md
    assert "Ship v1 — **100%** (1/1 tasks done)" in md


def test_report_lists_contradictions() -> None:
    repo, originals = _vault()
    repo.add_edge(Edge("t", "b", EdgeKind.CONTRADICTS))
    md = MarkdownReportRenderer().render(repo, originals)
    assert "## Open questions / needs review" in md
    assert "contradiction: Write the docs ⟷ Release" in md
