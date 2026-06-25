"""Tests for the deterministic update-intent detector (HeuristicUpdateDetector).

The detector maps a free-text capture to a target NoteStatus when it expresses progress on an
existing idea ("done: ...", "started ...", "up next ...", "reopen ..."), else None. Pure/offline.
"""

from __future__ import annotations

import pytest

from grandplan.core.models import NoteStatus
from grandplan.core.update_detect import UPDATE_STATUS, HeuristicUpdateDetector


@pytest.fixture
def detector() -> HeuristicUpdateDetector:
    return HeuristicUpdateDetector()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("done: built the resume", NoteStatus.DONE),
        ("finished the quarterly report", NoteStatus.DONE),
        ("completed the migration", NoteStatus.DONE),
        ("shipped the landing page", NoteStatus.DONE),
        ("wrapped up the deck", NoteStatus.DONE),
        ("✅ resume website", NoteStatus.DONE),
        ("[x] call the dentist", NoteStatus.DONE),
        ("started the landing page", NoteStatus.ACTIVE),
        ("began the migration sprint", NoteStatus.ACTIVE),
        ("working on the trading bot", NoteStatus.ACTIVE),
        ("in progress: the data migration", NoteStatus.ACTIVE),
        ("kicked off the redesign", NoteStatus.ACTIVE),
        ("up next: bug bounty research", NoteStatus.NEXT),
        ("queued the deploy", NoteStatus.NEXT),
        ("put the report on deck", NoteStatus.NEXT),
    ],
)
def test_detects_intent_status(
    detector: HeuristicUpdateDetector, text: str, expected: NoteStatus
) -> None:
    assert detector.detect(text) is expected


def test_reopen_beats_done_so_not_done_is_not_completion(
    detector: HeuristicUpdateDetector,
) -> None:
    # "not done"/"reopen" must win over the bare "done" substring → reopen → ACTIVE, never DONE.
    assert detector.detect("actually not done with the resume") is NoteStatus.ACTIVE
    assert detector.detect("reopen the resume task") is NoteStatus.ACTIVE
    assert detector.detect("the launch is no longer done") is NoteStatus.ACTIVE


def test_is_case_insensitive(detector: HeuristicUpdateDetector) -> None:
    assert detector.detect("DONE WITH THE RESUME") is NoteStatus.DONE


@pytest.mark.parametrize("text", ["", "   ", "a regular idea about cats", "buy more coffee beans"])
def test_no_update_intent_returns_none(detector: HeuristicUpdateDetector, text: str) -> None:
    assert detector.detect(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "restarted the server after a crash",  # "started" inside "restarted" must NOT fire
        "dequeued the stale jobs",  # "queue" inside "dequeued" must NOT fire
        "undone is not a word here either",  # "done" inside "undone" must NOT fire
    ],
)
def test_cues_do_not_fire_inside_larger_words(detector: HeuristicUpdateDetector, text: str) -> None:
    assert detector.detect(text) is None


def test_update_status_map_targets_only_existing_statuses() -> None:
    # The vocabulary never introduces a new status, and never reaches needs-review/superseded.
    assert set(UPDATE_STATUS.values()) <= {NoteStatus.DONE, NoteStatus.ACTIVE, NoteStatus.NEXT}
    assert UPDATE_STATUS["reopen"] is NoteStatus.ACTIVE


@pytest.mark.parametrize(
    "text",
    [
        # A re-paste / longer note that merely *mentions* a cue word deep in the body is content,
        # not a progress ping — it must NOT be read as a status update (the user re-captured an
        # unchanged note and it was wrongly marked done).
        "Research how we know the AI considered everything before we call it done and ship",
        "Figure out the right way to queue background jobs so the worker never stalls",
        "Notes on the launch plan: the landing page redesign is something I am working on later",
        "A checklist idea where each finished item gets a green check so progress is visible",
    ],
)
def test_buried_cue_in_a_longer_note_is_not_an_update(
    detector: HeuristicUpdateDetector, text: str
) -> None:
    assert detector.detect(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("done: built the resume generator", NoteStatus.DONE),
        ("done building the bug bounty finder tool", NoteStatus.DONE),
        ("up next: the prior-art research", NoteStatus.NEXT),
        ("started the landing page redesign", NoteStatus.ACTIVE),
        ("currently working on the onboarding flow", NoteStatus.ACTIVE),  # cue within the lead
    ],
)
def test_short_cue_led_pings_still_fire(
    detector: HeuristicUpdateDetector, text: str, expected: NoteStatus
) -> None:
    assert detector.detect(text) is expected
