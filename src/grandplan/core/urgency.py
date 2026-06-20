"""Taskwarrior-style urgency ranking for actionable notes (pure, offline, date-optional).

Orders the "what should I do now" list by a weighted score instead of arbitrary/topo order: lifecycle
status, note type, and — when a note has a concrete ISO due date and a reference `today` is supplied —
due proximity (overdue dominates, then due-today, then soon). Adopts Taskwarrior's tunable-coefficient
ranker (docs/research, area E). Pure: no clock is read here; the caller passes `today` (the I/O boundary
owns the real date), and a missing/unparseable due simply contributes nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date

from grandplan.core.models import Note, NoteStatus, NoteType

# Coefficients (relative weights; only their ordering matters for ranking). Tunable later.
_STATUS_WEIGHT: dict[NoteStatus, float] = {
    NoteStatus.ACTIVE: 4.0,
    NoteStatus.NEXT: 3.0,
    NoteStatus.NEEDS_REVIEW: 2.0,
    NoteStatus.INBOX: 1.0,
    NoteStatus.DONE: 0.0,
    NoteStatus.SUPERSEDED: 0.0,
}
_TYPE_WEIGHT: dict[NoteType, float] = {
    NoteType.TASK: 2.0,
    NoteType.DECISION: 1.5,
    NoteType.PROJECT: 1.0,
    NoteType.QUESTION: 1.0,
    NoteType.GOAL: 0.5,
}
_DUE_MAX = 6.0  # weight of an overdue item's due component


def urgency(note: Note, *, status: NoteStatus, today: date | None = None) -> float:
    """A non-negative urgency score for one note. DONE/SUPERSEDED are always 0 (not actionable)."""
    status_weight = _STATUS_WEIGHT.get(status, 1.0)
    if status_weight == 0.0:
        return 0.0
    return status_weight + _TYPE_WEIGHT.get(note.type, 0.0) + _due_weight(note.due, today)


def _due_weight(due: str | None, today: date | None) -> float:
    if due is None or today is None:
        return 0.0
    try:
        due_date = date.fromisoformat(due.strip())
    except ValueError:
        return 0.0  # free-form due ("Q3", "next friday") → no proximity signal
    days = (due_date - today).days
    if days < 0:
        return (
            _DUE_MAX + min(-days, 30) * 0.1
        )  # overdue: maximum pull, more overdue = higher (capped)
    if days <= 7:
        return 5.0 - days * 0.5  # due this week, sooner = higher (5.0 today → 1.5 in 7 days)
    return max(0.0, 2.0 - (days - 7) * 0.02)  # later: a small, decaying nudge


def rank_now(
    notes: Iterable[Note], status_by_id: Mapping[str, NoteStatus], *, today: date | None = None
) -> tuple[Note, ...]:
    """`notes` ranked by descending urgency; ties broken by id for determinism."""
    scored = [
        (note, urgency(note, status=status_by_id.get(note.id, NoteStatus.INBOX), today=today))
        for note in notes
    ]
    scored.sort(key=lambda item: (-item[1], item[0].id))
    return tuple(note for note, _ in scored)
