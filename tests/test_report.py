"""Tests for the vault health/run report."""

from __future__ import annotations

from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Edge, EdgeKind, Horizon, Note, NoteType, Original, Source
from grandplan.core.report import build_run_report, render_report
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore


def _seed(note: Note, text: str) -> tuple[InMemoryNoteRepository, InMemoryOriginalStore]:
    repo = InMemoryNoteRepository()
    originals = InMemoryOriginalStore()
    original = Original(id=note.original_id, text=text, source=Source(app="t"), created="2026")
    originals.add(original)
    repo.add_note(note, HashingEmbedder().embed(note.title))
    return repo, originals


def test_report_flags_no_structure_and_low_quality() -> None:
    raw = "buy milk"
    repo, originals = _seed(
        Note(id="a", original_id="oa", title="buy milk", body=raw, type=NoteType.IDEA, tags=()),
        raw,
    )
    report = build_run_report(repo, originals)

    assert report.note_count == 1
    assert report.structural_edges == 0
    assert report.low_quality  # un-organized note flagged
    assert report.isolated == ("buy milk",)

    text = render_report(report, organizer_label="heuristic baseline")
    assert "no structural edges" in text
    assert "never ran" in text  # 100% low-quality → the explicit diagnosis


def test_report_counts_structural_vs_semantic_edges() -> None:
    repo, originals = _seed(
        Note(
            id="a",
            original_id="oa",
            title="Goal: ship",
            body="organized",
            type=NoteType.GOAL,
            horizon=Horizon.GOAL,
            tags=("ship",),
        ),
        "the goal is to ship the product this quarter",
    )
    child = Note(
        id="b", original_id="ob", title="Task one", body="do it", type=NoteType.TASK, tags=("t",)
    )
    originals.add(
        Original(
            id="ob", text="do the first task carefully", source=Source(app="t"), created="2026"
        )
    )
    repo.add_note(child, HashingEmbedder().embed(child.title))
    repo.add_edge(Edge("b", "a", EdgeKind.PART_OF))
    repo.add_edge(Edge("b", "a", EdgeKind.RELATES))

    report = build_run_report(repo, originals)
    assert report.structural_edges == 1
    assert report.semantic_edges == 1
    assert report.isolated == ()  # both notes are connected
    assert not report.low_quality  # both organized with tags
