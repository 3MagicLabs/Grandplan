"""Tests for core.densify — offline mention -> wikilink suggestions."""

from __future__ import annotations

from grandplan.core.densify import suggest_mention_links
from grandplan.core.models import Note, NoteType


def _note(nid: str, title: str, body: str = "") -> Note:
    return Note(id=nid, original_id="o" + nid, title=title, body=body, type=NoteType.IDEA)


def test_title_mentioned_in_body_is_suggested() -> None:
    a = _note("a", "Research Plan", "today I worked on the Research Plan and it went well")
    b = _note("b", "Budget Spreadsheet", "numbers")
    assert (
        suggest_mention_links(a, [a, b, _note("c", "Research Plan referenced", "")]) == ()
    )  # a's body mentions no OTHER title
    target = _note("t", "Budget Spreadsheet", "")
    note = _note("n", "Daily log", "updated the Budget Spreadsheet figures")
    assert suggest_mention_links(note, [note, target]) == (target,)


def test_match_is_case_insensitive() -> None:
    target = _note("t", "Quarterly Review", "")
    note = _note("n", "Notes", "prepping for the quarterly review tomorrow")
    assert suggest_mention_links(note, [target]) == (target,)


def test_only_whole_word_phrases_match() -> None:
    target = _note("t", "cat", "")
    note = _note("n", "Notes", "the category is broad")  # 'cat' inside 'category' must NOT match
    assert suggest_mention_links(note, [target], min_chars=3) == ()


def test_a_note_never_links_to_itself() -> None:
    note = _note("n", "Self Reference", "this is the Self Reference note")
    assert suggest_mention_links(note, [note]) == ()


def test_short_titles_are_skipped_as_noise() -> None:
    target = _note("t", "AI", "")  # 2 chars — too short, skipped by default min_chars=3
    note = _note("n", "Notes", "AI is everywhere in AI research")
    assert suggest_mention_links(note, [target]) == ()


def test_each_target_suggested_once_in_stable_order() -> None:
    t1 = _note("t1", "Alpha Project", "")
    t2 = _note("t2", "Beta Project", "")
    note = _note("n", "Log", "Beta Project then Alpha Project then Beta Project again")
    # Stable by the `others` iteration order, each once.
    assert suggest_mention_links(note, [t1, t2]) == (t1, t2)
