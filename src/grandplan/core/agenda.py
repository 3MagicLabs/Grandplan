"""The daily 'Today' digest — a pure projection of the actionable notes (offline).

Answers "what should I do today": overdue items, items due today, then the urgency-ranked rest. Adopts
the org-mode/Khoj daily-agenda pattern (docs/research, area E). Pure and clock-free — the caller passes
the actionable notes (typically `build_plan(repo).now`), a status map, and `today`; rendering links by
filename (never id), consistent with the rest of the vault.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from grandplan.core.models import Note, NoteStatus
from grandplan.core.urgency import rank_now
from grandplan.core.vault import note_filename

_MARKER = "Generated daily agenda"


@dataclass(frozen=True)
class Agenda:
    """Actionable notes partitioned for the day, each list urgency-ranked."""

    overdue: tuple[Note, ...]
    due_today: tuple[Note, ...]
    next_up: tuple[Note, ...]


def build_agenda(
    now_notes: Iterable[Note], status_by_id: Mapping[str, NoteStatus], *, today: date
) -> Agenda:
    """Partition actionable notes into overdue / due-today / next-up, each urgency-ranked.

    `now_notes` are the unblocked actionable notes (e.g. `build_plan(repo).now`)."""
    overdue: list[Note] = []
    due_today: list[Note] = []
    next_up: list[Note] = []
    for note in now_notes:
        due = _due_date(note.due)
        if due is not None and due < today:
            overdue.append(note)
        elif due is not None and due == today:
            due_today.append(note)
        else:
            next_up.append(note)

    def rank(notes: list[Note]) -> tuple[Note, ...]:
        return rank_now(notes, status_by_id, today=today)

    return Agenda(overdue=rank(overdue), due_today=rank(due_today), next_up=rank(next_up))


def _due_date(due: str | None) -> date | None:
    if due is None:
        return None
    try:
        return date.fromisoformat(due.strip())
    except ValueError:
        return None  # free-form due ("Q3") is not a concrete day


def render_agenda(agenda: Agenda, today: date) -> str:
    """Render the agenda as Obsidian-friendly Markdown (filename links, regenerated each save)."""
    lines = [
        f"# Today — {today.isoformat()}",
        "",
        f"> {_MARKER} — a projection of your actionable notes. Edit the notes, not this file.",
    ]
    sections = (
        ("## Overdue", agenda.overdue),
        ("## Due today", agenda.due_today),
        ("## Next up", agenda.next_up),
    )
    empty = True
    for heading, notes in sections:
        lines += ["", heading]
        if notes:
            empty = False
            lines += [f"- [ ] [[{note_filename(note)}|{note.title}]]" for note in notes]
        else:
            lines.append("_Nothing here._")
    if empty:
        lines += [
            "",
            "Nothing actionable today — capture a thought or pick something from the plan.",
        ]
    return "\n".join(lines) + "\n"
