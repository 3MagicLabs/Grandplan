"""Tests for organize-quality checks (QAS-8)."""

from __future__ import annotations

from grandplan.core.models import Note, NoteType, Original, Source
from grandplan.core.quality import is_low_quality, note_quality_issues


def _original(text: str) -> Original:
    return Original.capture(text, Source(app="t"), "2026-06-17T00:00:00Z")


def _note(*, title: str, body: str, tags: tuple[str, ...] = ("topic",)) -> Note:
    return Note(id="n", original_id="o", title=title, body=body, type=NoteType.IDEA, tags=tags)


def test_well_organized_note_has_no_issues() -> None:
    original = _original("cloud ai is unsustainable; build a local optimization layer instead")
    note = _note(
        title="Local optimization layer",
        body="**Summary:** move inference local.\n\n- cost\n- privacy",
        tags=("ai", "local"),
    )
    assert note_quality_issues(note, original) == ()
    assert not is_low_quality(note, original)


def test_verbatim_truncated_title_is_flagged() -> None:
    raw = (
        "cloud ai are not sustainable, need to figure out a way to make some local optimization now"
    )
    original = _original(raw)
    note = _note(title=raw[:80], body="organized body here", tags=("ai",))
    issues = note_quality_issues(note, original)
    assert any("raw capture" in i for i in issues)
    assert any("truncated mid-word" in i for i in issues)


def test_unorganized_body_and_missing_tags_are_flagged() -> None:
    raw = "buy milk"
    original = _original(raw)
    note = _note(title="Groceries", body=raw, tags=())
    issues = note_quality_issues(note, original)
    assert any("unmodified capture" in i for i in issues)
    assert any("no topical tags" in i for i in issues)
    assert is_low_quality(note, original)
