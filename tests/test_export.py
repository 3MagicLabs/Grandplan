"""Tests for productivity exports — Markdown Tasks + CSV (offline, deterministic)."""

from __future__ import annotations

from grandplan.core.export import to_csv, to_markdown_tasks
from grandplan.core.models import Note, NoteStatus, NoteType


def _note(
    nid: str,
    title: str,
    *,
    note_type: NoteType = NoteType.TASK,
    status: NoteStatus = NoteStatus.INBOX,
    due: str | None = None,
    tags: tuple[str, ...] = (),
) -> Note:
    return Note(
        id=nid,
        original_id=f"o{nid}",
        title=title,
        body="b",
        type=note_type,
        status=status,
        due=due,
        tags=tags,
    )


def test_markdown_tasks_renders_checkboxes_and_dates() -> None:
    notes = [
        _note("a", "Write spec", due="2026-07-01", tags=("docs",)),
        _note("b", "Ship it", status=NoteStatus.DONE),
    ]
    md = to_markdown_tasks(notes)
    assert "- [ ] Write spec 📅 2026-07-01 #docs" in md
    assert "- [x] Ship it" in md


def test_markdown_tasks_orders_by_due_then_title() -> None:
    notes = [
        _note("a", "Zebra", due="2026-08-01"),
        _note("b", "Apple", due="2026-07-01"),
        _note("c", "Undated"),
    ]
    md = to_markdown_tasks(notes)
    assert md.index("Apple") < md.index("Zebra") < md.index("Undated")


def test_markdown_tasks_omits_non_actionable() -> None:
    notes = [_note("a", "An idea", note_type=NoteType.IDEA), _note("b", "Do it")]
    md = to_markdown_tasks(notes)
    assert "Do it" in md and "An idea" not in md


def test_markdown_tasks_empty() -> None:
    assert "_No tasks._" in to_markdown_tasks([])


def test_csv_has_header_and_rows() -> None:
    notes = [_note("a", "Buy milk", due="2026-07-01", tags=("home", "errand"))]
    csv_text = to_csv(notes)
    lines = csv_text.strip().splitlines()
    assert lines[0] == "id,title,type,status,horizon,due,tags"
    assert lines[1] == "a,Buy milk,task,inbox,action,2026-07-01,home;errand"


def test_csv_quotes_titles_with_commas() -> None:
    csv_text = to_csv([_note("a", "Buy milk, eggs")])
    assert '"Buy milk, eggs"' in csv_text


def test_csv_sorted_by_title() -> None:
    csv_text = to_csv([_note("a", "Zebra"), _note("b", "Apple")])
    body = csv_text.strip().splitlines()[1:]
    assert body[0].split(",")[1] == "Apple"
