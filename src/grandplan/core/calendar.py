"""iCalendar (.ics) export — a local, offline calendar connector (ROADMAP theme B).

Notes that carry a `due` date become all-day events in a standards-compliant RFC 5545 iCalendar
feed that any calendar app (Apple / Google / Outlook) can **subscribe to** — pointed at a local
file, so it is **zero-egress** (QAS-1) and updates whenever the file is rewritten. Pure and
deterministic: no network, no third-party deps, and the timestamp is caller-supplied (no hidden
clock), so the output is fully testable.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from grandplan.core.models import Note, NoteStatus

PRODID = "-//grandplan//calendar//EN"
# Accepted `due` shapes (the field is free-form text set by the organizer/edits); first match wins.
_DATE_FORMATS = ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d")


def parse_due(due: str) -> str | None:
    """An iCalendar DATE (`YYYYMMDD`) parsed from a free-form `due` string, or None if not a date."""
    stripped = due.strip()
    for candidate in (stripped, stripped[:10]):  # whole, then an ISO date prefix (drops any time)
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).strftime("%Y%m%d")
            except ValueError:
                continue
    return None


def is_scheduled(note: Note) -> bool:
    """True when a note has a parseable `due` date (so it can become a calendar event)."""
    return note.due is not None and parse_due(note.due) is not None


def to_ics(notes: Iterable[Note], *, dtstamp: str) -> str:
    """Render the scheduled notes as a VCALENDAR string (CRLF-terminated, RFC 5545).

    `dtstamp` is a caller-supplied UTC stamp (`YYYYMMDDTHHMMSSZ`) — no hidden clock. Notes without a
    parseable `due` are skipped. Tasks already done are marked but still listed (a record of when).
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:grandplan",
    ]
    for note in notes:
        date = parse_due(note.due) if note.due is not None else None
        if date is None:
            continue
        lines += _event_lines(note, date, dtstamp)
    lines.append("END:VCALENDAR")
    return "".join(f"{_fold(line)}\r\n" for line in lines)


def _event_lines(note: Note, date: str, dtstamp: str) -> list[str]:
    done = note.status is NoteStatus.DONE
    summary = f"{'✔ ' if done else ''}{note.title}"
    lines = [
        "BEGIN:VEVENT",
        f"UID:{note.id}@grandplan",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;VALUE=DATE:{date}",  # all-day event on the due date (no DTEND ⇒ a single day)
        f"SUMMARY:{_escape(summary)}",
        f"CATEGORIES:{_escape(note.type.value)}",
        f"STATUS:{'COMPLETED' if done else 'CONFIRMED'}",
    ]
    body = note.body.strip()
    if body:
        lines.append(f"DESCRIPTION:{_escape(body[:500])}")
    lines.append("END:VEVENT")
    return lines


def _escape(text: str) -> str:
    """Escape per RFC 5545 §3.3.11 (backslash, semicolon, comma, newline; strip CR)."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r", "")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold a content line to ≤75 octets with CRLF + space (RFC 5545 §3.1), UTF-8-safe."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    chunks: list[bytes] = []
    limit = 75  # the first physical line; continuation lines carry a leading space → 74 of content
    while len(raw) > limit:
        cut = limit
        while cut > 0 and (raw[cut] & 0xC0) == 0x80:  # don't split a multi-byte UTF-8 sequence
            cut -= 1
        chunks.append(raw[:cut])
        raw = raw[cut:]
        limit = 74
    chunks.append(raw)
    return "\r\n ".join(chunk.decode("utf-8") for chunk in chunks)
