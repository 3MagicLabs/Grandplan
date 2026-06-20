"""Productivity exports — render notes into other tools' formats (ROADMAP theme B, local/offline).

Two stand-alone, zero-egress exporters that take a vault somewhere else:

- **Markdown Tasks** — a `- [ ]`/`- [x]` checklist with the Obsidian/GitHub task convention plus a
  `📅 <due>` date marker, so tasks drop straight into the Obsidian *Tasks* plugin or any Markdown todo.
- **CSV** — one row per note (id, title, type, status, horizon, due, tags), for a spreadsheet or import.

Both are pure functions of the derived current notes — offline, deterministic — so they're fully
gated and the offline-egress invariant (QAS-1) is never touched.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from grandplan.core.models import Note, NoteStatus, NoteType

# Task-like notes that belong in a checklist (ideas/references/entities aren't actionable items).
_TASK_TYPES = {NoteType.TASK, NoteType.PROJECT, NoteType.GOAL}
_DONE = {NoteStatus.DONE, NoteStatus.SUPERSEDED}

_CSV_HEADER = ("id", "title", "type", "status", "horizon", "due", "tags")


def to_markdown_tasks(notes: Iterable[Note]) -> str:
    """Render actionable notes as a Markdown task list (`- [ ] title 📅 due`), checked when done.

    Order-stable: by due date (undated last), then title. Non-actionable notes are omitted.
    """
    tasks = sorted(
        (note for note in notes if note.type in _TASK_TYPES),
        key=lambda n: (n.due or "9999-99-99", n.title),
    )
    lines = ["# Tasks", ""]
    if not tasks:
        lines.append("_No tasks._")
        return "\n".join(lines) + "\n"
    for note in tasks:
        box = "x" if note.status in _DONE else " "
        due = f" 📅 {note.due}" if note.due else ""
        tags = "".join(f" #{tag}" for tag in note.tags)
        lines.append(f"- [{box}] {note.title}{due}{tags}")
    return "\n".join(lines) + "\n"


def to_csv(notes: Iterable[Note]) -> str:
    """Render every note as a CSV table (one row per note), sorted by title then id (stable)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_HEADER)
    for note in sorted(notes, key=lambda n: (n.title, n.id)):
        writer.writerow(
            (
                note.id,
                note.title,
                note.type.value,
                note.status.value,
                note.horizon.value,
                note.due or "",
                ";".join(note.tags),
            )
        )
    return buffer.getvalue()
