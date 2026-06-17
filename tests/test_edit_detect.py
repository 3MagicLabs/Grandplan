"""Tests for the deterministic edit-intent detector (HeuristicEditDetector).

It recognises the two edits that can be extracted offline without an LLM — a **due** change and a
**retitle** — and returns the corresponding NoteEdit; everything else is None (a new note / an LLM
job). Pure/offline.
"""

from __future__ import annotations

import pytest

from grandplan.core.edit_detect import HeuristicEditDetector
from grandplan.core.models import NoteEdit


@pytest.fixture
def detector() -> HeuristicEditDetector:
    return HeuristicEditDetector()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("launch slipped to Q3", NoteEdit(due="Q3")),
        ("the report is due 2026-09-01", NoteEdit(due="2026-09-01")),
        ("deadline: next friday", NoteEdit(due="next friday")),
        ("pushed to next week", NoteEdit(due="next week")),
        ("rescheduled to Q4", NoteEdit(due="Q4")),
        ("due at next friday", NoteEdit(due="next friday")),  # leading preposition is consumed
        ("rename the resume task to CV", NoteEdit(title="CV")),
        ("retitle to Resume v2", NoteEdit(title="Resume v2")),
        ("call it the master plan", NoteEdit(title="the master plan")),
        ("rename it to back to basics", NoteEdit(title="back to basics")),  # title keeps its "to"
    ],
)
def test_detects_due_and_retitle(
    detector: HeuristicEditDetector, text: str, expected: NoteEdit
) -> None:
    assert detector.detect(text) == expected


@pytest.mark.parametrize("text", ["I moved to London", "pushed the button to start"])
def test_vague_motion_phrases_are_not_treated_as_due(
    detector: HeuristicEditDetector, text: str
) -> None:
    # "moved to" is excluded entirely; "pushed" only counts as "pushed to" (deadline-specific).
    assert detector.detect(text) is None


def test_retitle_takes_precedence_over_a_trailing_due_word() -> None:
    # A clear retitle wins even if a date-ish word appears; one capture = one heuristic edit.
    assert detector_detect("rename it to Q3 planning doc") == NoteEdit(title="Q3 planning doc")


def detector_detect(text: str) -> NoteEdit | None:
    return HeuristicEditDetector().detect(text)


@pytest.mark.parametrize(
    "text", ["", "   ", "a brand new idea about coffee", "it's overdue already"]
)
def test_no_edit_intent_returns_none(detector: HeuristicEditDetector, text: str) -> None:
    assert detector.detect(text) is None
