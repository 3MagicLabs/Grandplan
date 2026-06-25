"""Tests for core.urgency — Taskwarrior-style actionable ranking (pure, date-optional)."""

from __future__ import annotations

from datetime import date

from grandplan.core.models import Note, NoteStatus, NoteType
from grandplan.core.urgency import rank_now, urgency

_TODAY = date(2026, 6, 20)


def _n(nid: str, *, type: NoteType = NoteType.TASK, due: str | None = None) -> Note:
    return Note(id=nid, original_id="o" + nid, title=nid, body="b", type=type, due=due)


def test_active_outranks_next_outranks_inbox_same_due() -> None:
    a = _n("a")
    assert urgency(a, status=NoteStatus.ACTIVE) > urgency(a, status=NoteStatus.NEXT)
    assert urgency(a, status=NoteStatus.NEXT) > urgency(a, status=NoteStatus.INBOX)


def test_due_proximity_drives_urgency() -> None:
    overdue = _n("o", due="2026-06-10")
    today = _n("t", due="2026-06-20")
    soon = _n("s", due="2026-06-25")
    later = _n("l", due="2026-12-01")
    none = _n("n", due=None)

    def u(note: Note) -> float:
        return urgency(note, status=NoteStatus.NEXT, today=_TODAY)

    assert u(overdue) > u(today) > u(soon) > u(later) >= u(none)


def test_unparseable_due_is_treated_as_no_date() -> None:
    assert urgency(_n("q", due="next friday"), status=NoteStatus.NEXT, today=_TODAY) == urgency(
        _n("q", due=None), status=NoteStatus.NEXT, today=_TODAY
    )


def test_done_and_superseded_have_zero_urgency() -> None:
    assert urgency(_n("d"), status=NoteStatus.DONE) == 0.0
    assert urgency(_n("x"), status=NoteStatus.SUPERSEDED) == 0.0


def test_rank_now_orders_highest_urgency_first() -> None:
    overdue = _n("overdue", due="2026-06-01")
    plain = _n("plain")
    status = {"overdue": NoteStatus.NEXT, "plain": NoteStatus.INBOX}
    ranked = rank_now([plain, overdue], status, today=_TODAY)
    assert [n.id for n in ranked] == ["overdue", "plain"]


def test_rank_now_is_deterministic_on_ties() -> None:
    a, b = _n("a"), _n("b")
    status = {"a": NoteStatus.NEXT, "b": NoteStatus.NEXT}
    assert [n.id for n in rank_now([b, a], status)] == ["a", "b"]  # tie broken by id
