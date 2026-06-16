"""Tests for the deterministic HeuristicOrganizer baseline."""

from __future__ import annotations

import pytest

from grandplan.core.models import NoteType, Original, Source
from grandplan.core.organize import HeuristicOrganizer

_CREATED = "2026-06-15T00:00:00Z"


def _capture(text: str) -> Original:
    return Original.capture(text, Source(app="Notepad"), _CREATED)


def test_title_is_first_nonempty_line() -> None:
    proposed = HeuristicOrganizer().organize(_capture("\n\n  Project kickoff  \nrest"))
    assert proposed.title == "Project kickoff"


def test_title_is_truncated_to_max() -> None:
    assert len(HeuristicOrganizer().organize(_capture("x" * 200)).title) == 80


def test_body_preserves_stripped_text_and_links_original() -> None:
    original = _capture("a thought worth keeping")
    proposed = HeuristicOrganizer().organize(original)
    assert proposed.body == "a thought worth keeping"
    assert proposed.original_id == original.id


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("TODO submit the report by the deadline", NoteType.TASK),
        ("What if we tried a new approach?", NoteType.QUESTION),
        ("My objective is long-term growth", NoteType.GOAL),
        ("a quiet interesting observation", NoteType.IDEA),
    ],
)
def test_type_inference(text: str, expected: NoteType) -> None:
    assert HeuristicOrganizer().organize(_capture(text)).type is expected


def test_keywords_exclude_stopwords_and_short_tokens() -> None:
    proposed = HeuristicOrganizer().organize(_capture("the alpha alpha beta of it"))
    assert "the" not in proposed.tags
    assert "it" not in proposed.tags
    assert proposed.tags[0] == "alpha"
