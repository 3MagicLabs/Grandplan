"""Productivity exports — render notes into other tools' formats (ROADMAP theme B, local/offline).

Three stand-alone, zero-egress exporters that take a vault somewhere else:

- **Markdown Tasks** — a `- [ ]`/`- [x]` checklist with the Obsidian/GitHub task convention plus a
  `📅 <due>` date marker, so tasks drop straight into the Obsidian *Tasks* plugin or any Markdown todo.
- **CSV** — one row per note (id, title, type, status, horizon, due, tags), for a spreadsheet or import.
- **Todoist** — a CSV in Todoist's import-template format (TYPE/CONTENT/PRIORITY/DATE/…), so your
  open tasks import directly into a Todoist project.

All are pure functions of the derived current notes — offline, deterministic — so they're fully
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

# Todoist's CSV import template columns (in order). See Todoist's "import from CSV" template.
_TODOIST_HEADER = (
    "TYPE",
    "CONTENT",
    "DESCRIPTION",
    "PRIORITY",
    "INDENT",
    "AUTHOR",
    "RESPONSIBLE",
    "DATE",
    "DATE_LANG",
    "TIMEZONE",
)
# Todoist priority: 4 = highest (p1) … 1 = normal (p4). Map by lifecycle so what's "active" stands out.
_TODOIST_PRIORITY = {NoteStatus.ACTIVE: "4", NoteStatus.NEXT: "3"}


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


def to_todoist_csv(notes: Iterable[Note]) -> str:
    """Render OPEN actionable notes as a Todoist-import CSV (its template columns).

    Only open tasks/projects/goals are exported (Todoist import is for things still to do; done
    items are skipped). Priority follows lifecycle (active highest, then next, else normal); the due
    date maps to Todoist's DATE column. Order-stable by due then title.
    """
    tasks = sorted(
        (note for note in notes if note.type in _TASK_TYPES and note.status not in _DONE),
        key=lambda n: (n.due or "9999-99-99", n.title),
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_TODOIST_HEADER)
    for note in tasks:
        writer.writerow(
            (
                "task",
                note.title,
                note.body,
                _TODOIST_PRIORITY.get(note.status, "1"),
                "1",  # indent: all top-level (grandplan's hierarchy is in the vault, not flattened here)
                "",  # author
                "",  # responsible
                note.due or "",
                "en",  # date language
                "",  # timezone (Todoist infers)
            )
        )
    return buffer.getvalue()
