"""Tests for the iCalendar (.ics) export connector."""

from __future__ import annotations

from grandplan.core.calendar import is_scheduled, parse_due, to_ics
from grandplan.core.models import Note, NoteStatus, NoteType

_STAMP = "20260618T000000Z"


def _note(*, title: str = "Ship it", due: str | None = "2026-07-01", **kw: object) -> Note:
    return Note(
        id=kw.get("id", "n1"),
        original_id="o",
        title=title,
        body="do the thing",
        type=NoteType.TASK,
        due=due,
    )  # type: ignore[arg-type]


def test_parse_due_accepts_common_shapes_and_rejects_junk() -> None:
    assert parse_due("2026-07-01") == "20260701"
    assert parse_due("2026-07-01T09:30:00Z") == "20260701"  # ISO prefix
    assert parse_due("20260701") == "20260701"
    assert parse_due("someday") is None
    assert parse_due("") is None


def test_to_ics_emits_a_valid_all_day_vevent() -> None:
    ics = to_ics([_note()], dtstamp=_STAMP)
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.endswith("END:VCALENDAR\r\n")
    assert "VERSION:2.0\r\n" in ics
    assert "BEGIN:VEVENT\r\n" in ics
    assert "UID:n1@grandplan\r\n" in ics
    assert "DTSTART;VALUE=DATE:20260701\r\n" in ics
    assert "SUMMARY:Ship it\r\n" in ics
    assert f"DTSTAMP:{_STAMP}\r\n" in ics


def test_to_ics_skips_notes_without_a_parseable_due() -> None:
    notes = [
        _note(id="a", due=None),
        _note(id="b", due="not a date"),
        _note(id="c", due="2026-08-09"),
    ]
    ics = to_ics(notes, dtstamp=_STAMP)
    assert ics.count("BEGIN:VEVENT") == 1  # only the one with a real date
    assert "DTSTART;VALUE=DATE:20260809\r\n" in ics


def test_to_ics_escapes_special_characters() -> None:
    ics = to_ics([_note(title="Pay; tax, now")], dtstamp=_STAMP)
    assert "SUMMARY:Pay\\; tax\\, now\r\n" in ics  # ';' and ',' escaped per RFC 5545


def test_done_task_is_marked_completed() -> None:
    note = Note(
        id="d",
        original_id="o",
        title="filed",
        body="b",
        type=NoteType.TASK,
        status=NoteStatus.DONE,
        due="2026-07-01",
    )
    ics = to_ics([note], dtstamp=_STAMP)
    assert "STATUS:COMPLETED\r\n" in ics
    assert "SUMMARY:✔ filed\r\n" in ics


def test_long_line_is_folded_to_75_octets() -> None:
    note = _note(title="x" * 200)
    ics = to_ics([note], dtstamp=_STAMP)
    # Every physical line must be ≤ 75 octets; continuations start with a single space.
    for line in ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    assert "\r\n " in ics  # a fold actually happened


def test_is_scheduled_predicate() -> None:
    assert is_scheduled(_note(due="2026-07-01"))
    assert not is_scheduled(_note(due=None))
    assert not is_scheduled(_note(due="whenever"))
