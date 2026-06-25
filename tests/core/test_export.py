"""Tests for productivity exports — Markdown Tasks + CSV + Todoist (offline, deterministic)."""

from __future__ import annotations

from grandplan.core.export import to_csv, to_markdown_tasks, to_todoist_csv
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


def test_todoist_csv_header_and_open_task_row() -> None:
    notes = [
        _note("a", "Write spec", status=NoteStatus.ACTIVE, due="2026-07-01"),
        _note("b", "Old thing", status=NoteStatus.DONE),  # done → omitted
    ]
    out = to_todoist_csv(notes)
    lines = out.strip().splitlines()
    assert (
        lines[0]
        == "TYPE,CONTENT,DESCRIPTION,PRIORITY,INDENT,AUTHOR,RESPONSIBLE,DATE,DATE_LANG,TIMEZONE"
    )
    # one open task row; active → priority 4; due maps to DATE
    assert "task,Write spec,b,4,1,,,2026-07-01,en," in out
    assert "Old thing" not in out  # done task excluded


def test_todoist_csv_priority_by_status() -> None:
    notes = [
        _note("a", "Active one", status=NoteStatus.ACTIVE),
        _note("b", "Next one", status=NoteStatus.NEXT),
        _note("c", "Inbox one", status=NoteStatus.INBOX),
    ]
    rows = {
        r.split(",")[1]: r.split(",")[3] for r in to_todoist_csv(notes).strip().splitlines()[1:]
    }
    assert rows["Active one"] == "4"
    assert rows["Next one"] == "3"
    assert rows["Inbox one"] == "1"


def test_todoist_csv_omits_non_actionable_and_empty() -> None:
    assert to_todoist_csv([_note("a", "an idea", note_type=NoteType.IDEA)]).strip().count("\n") == 0
