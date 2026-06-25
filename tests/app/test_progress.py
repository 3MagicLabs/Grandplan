"""Tests for the pure capture-progress mapping (the GUI widget renders ProgressView)."""

from __future__ import annotations

from grandplan.app.coordinator import CaptureStatus, Stage
from grandplan.app.progress import progress_for


def _view(stage: Stage, detail: str = ""):  # type: ignore[no-untyped-def]
    return progress_for(CaptureStatus(stage=stage, detail=detail))


def test_busy_stages_animate_and_advance() -> None:
    capturing = _view(Stage.CAPTURING)
    analyzing = _view(Stage.ANALYZING, "organizing with local AI")
    assert capturing.busy and capturing.visible and not capturing.terminal
    assert "Organizing" in analyzing.title and analyzing.detail == "organizing with local AI"
    assert analyzing.percent > capturing.percent  # the bar advances through the pipeline


def test_awaiting_review_is_not_busy() -> None:
    view = _view(Stage.AWAITING_REVIEW)
    assert not view.busy  # waiting on the human, not processing
    assert view.percent == 70 and view.visible and not view.terminal


def test_saved_is_terminal_and_ok() -> None:
    view = _view(Stage.SAVED)
    assert view.terminal and view.ok and view.percent == 100 and not view.busy


def test_failed_is_terminal_and_not_ok() -> None:
    view = _view(Stage.FAILED, "boom")
    assert view.terminal and not view.ok
    assert view.detail == "boom"


def test_idle_hides_the_popup() -> None:
    assert _view(Stage.IDLE).visible is False


def test_empty_selection_is_a_terminal_message() -> None:
    view = _view(Stage.EMPTY)
    assert view.terminal and view.ok and view.visible
    assert "Nothing" in view.title


def test_every_stage_maps_without_error() -> None:
    # Robustness: a new Stage must not break the popup — every stage yields a renderable view.
    for stage in Stage:
        view = _view(stage)
        assert isinstance(view.title, str) and view.title
        assert view.percent == -1 or 0 <= view.percent <= 100
