"""Tests for the pure capture-progress mapping (the GUI widget renders ProgressView)."""

from __future__ import annotations

from grandplan.app.coordinator import CaptureStatus, ItemState, QueueItem, Stage
from grandplan.app.progress import PIPELINE_STAGES, progress_for, row_for


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


def test_enriched_is_tray_only_and_never_terminal() -> None:
    # Background enrichment is routine housekeeping: it must update the tray tooltip (the live
    # backlog count) without ever raising the popup or reading as a finished capture.
    view = _view(Stage.ENRICHED)
    assert view.visible is False and not view.terminal and not view.busy and view.ok


def test_queued_is_tray_only_and_not_terminal() -> None:
    # A note joining the line drives the live queue view, never the single-note popup — so it must
    # not raise/hide the popup as a "real" stage would (visible False), nor read as busy/finished.
    view = _view(Stage.QUEUED)
    assert view.visible is False and not view.terminal and not view.busy and view.ok


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


def test_progress_view_surfaces_queue_depth() -> None:
    # The popup can show how many captures are still waiting behind the current one (#3).
    assert progress_for(CaptureStatus(stage=Stage.ANALYZING, detail="x", pending=3)).queued == 3
    assert progress_for(CaptureStatus(stage=Stage.ANALYZING)).queued == 0  # default: none waiting


# -- queue view rows (US-7 "carousel") ------------------------------------------------------------


def _item(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        id="1", snippet="a captured thought", source="grandplan", stage=None, position=0, detail=""
    )
    base.update(kw)
    return QueueItem(**base)  # type: ignore[arg-type]


def test_row_for_queued_shows_place_in_line() -> None:
    row = row_for(_item(state=ItemState.QUEUED, position=3))
    assert row.section == "queued"
    assert row.line == "#3 in line"
    assert row.steps == ()  # no step strip until it is being made
    assert row.icon == "🖥️"  # desktop provenance


def test_row_for_in_flight_lights_up_the_current_step() -> None:
    row = row_for(_item(state=ItemState.IN_FLIGHT, stage=Stage.ANALYZING))
    assert row.section == "now"
    assert row.percent == -1  # busy → animated/indeterminate bar
    labels = [label for label, _ in row.steps]
    assert labels == ["capture", "analyze", "review", "commit", "save"]
    states = {label: state for label, state in row.steps}
    assert states["capture"] == "done" and states["analyze"] == "active"
    assert states["review"] == "todo" and states["save"] == "todo"


def test_row_for_awaiting_review_is_determinate() -> None:
    row = row_for(_item(state=ItemState.IN_FLIGHT, stage=Stage.AWAITING_REVIEW))
    assert row.percent == 70  # resting on the human, not animating
    states = {label: state for label, state in row.steps}
    assert states["review"] == "active" and states["analyze"] == "done"


def test_row_for_phone_source_uses_the_phone_icon() -> None:
    row = row_for(_item(state=ItemState.QUEUED, source="phone", position=1))
    assert row.icon == "📱"


def test_row_for_finished_notes_land_in_the_done_band() -> None:
    saved = row_for(_item(state=ItemState.SAVED))
    failed = row_for(_item(state=ItemState.FAILED))
    discarded = row_for(_item(state=ItemState.DISCARDED))
    assert saved.section == "done" and saved.line == "saved ✓" and saved.percent == 100 and saved.ok
    assert failed.section == "done" and not failed.ok  # tinted red
    assert discarded.line == "discarded" and discarded.steps == ()


def test_pipeline_stages_cover_every_step_label() -> None:
    # The strip a row renders must have a label for every pipeline stage (no KeyError at render).
    for stage in PIPELINE_STAGES:
        row = row_for(_item(state=ItemState.IN_FLIGHT, stage=stage))
        assert len(row.steps) == len(PIPELINE_STAGES)
