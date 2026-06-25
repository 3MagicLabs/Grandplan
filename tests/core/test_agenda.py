"""Tests for core.agenda — the daily 'Today' digest (pure projection)."""

from __future__ import annotations

from datetime import date

from grandplan.core.agenda import build_agenda, render_agenda
from grandplan.core.models import Note, NoteStatus, NoteType

_TODAY = date(2026, 6, 20)


def _n(nid: str, title: str, *, due: str | None = None) -> Note:
    return Note(id=nid, original_id="o" + nid, title=title, body="b", type=NoteType.TASK, due=due)


def _agenda(notes):  # type: ignore[no-untyped-def]
    status = {n.id: NoteStatus.NEXT for n in notes}
    return build_agenda(notes, status, today=_TODAY)


def test_partitions_overdue_due_today_and_next_up() -> None:
    overdue = _n("o", "Pay invoice", due="2026-06-10")
    today = _n("t", "Call dentist", due="2026-06-20")
    later = _n("l", "Plan trip", due="2026-08-01")
    undated = _n("u", "Read paper")
    ag = _agenda([later, undated, today, overdue])
    assert [n.id for n in ag.overdue] == ["o"]
    assert [n.id for n in ag.due_today] == ["t"]
    assert {n.id for n in ag.next_up} == {"l", "u"}  # everything else, urgency-ranked


def test_overdue_sorted_by_urgency_most_overdue_first() -> None:
    a = _n("a", "A", due="2026-06-18")
    b = _n("b", "B", due="2026-06-01")  # more overdue → higher urgency
    ag = _agenda([a, b])
    assert [n.id for n in ag.overdue] == ["b", "a"]


def test_render_is_markdown_with_filename_links_and_marker() -> None:
    ag = _agenda([_n("o", "Pay invoice", due="2026-06-10"), _n("u", "Read paper")])
    md = render_agenda(ag, _TODAY)
    assert "# Today — 2026-06-20" in md
    assert "Generated daily agenda" in md  # marker (foreign-file guard recognises our file)
    assert "## Overdue" in md and "## Next up" in md
    assert "[[pay-invoice|Pay invoice]]" in md  # filename link, never an id
    assert "- [ ] " in md  # actionable checkbox items


def test_empty_agenda_renders_without_crashing() -> None:
    md = render_agenda(build_agenda([], {}, today=_TODAY), _TODAY)
    assert "# Today — 2026-06-20" in md
    assert "Nothing" in md
