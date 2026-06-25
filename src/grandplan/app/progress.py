"""Pure mapping from a capture Stage to a visual ProgressView (message, %, busy, terminal).

Kept out of the Qt layer so the "what should the progress popup show" logic is fully unit-tested
(CS130 testability: controllability + observability); the GUI widget is a thin renderer of
ProgressView. Each capture moves CAPTURING → ANALYZING → AWAITING_REVIEW → COMMITTING → SAVED, with
EMPTY / DISCARDED / FAILED as terminal outcomes — so the user always sees what is happening.
"""

from __future__ import annotations

from dataclasses import dataclass

from grandplan.app.coordinator import CaptureStatus, Stage


@dataclass(frozen=True)
class ProgressView:
    """Everything the progress popup needs to render one capture-status update."""

    title: str  # short headline, e.g. "Organizing with local AI…"
    detail: str  # the status detail (e.g. the note title or error text)
    percent: int  # 0..100 for a determinate bar; -1 = indeterminate (still working, unknown ETA)
    busy: bool  # actively processing → animate the bar
    visible: bool  # should the popup be shown at all (False = idle/ready → hide it)
    terminal: bool  # the capture finished (success or failure) → auto-hide shortly after
    ok: bool  # success vs failure → colour the bar green vs red
    queued: int = 0  # captures still waiting behind this one → popup can show "+N waiting"


# Rough percent per pipeline stage so the bar advances monotonically through a capture.
_PERCENT: dict[Stage, int] = {
    Stage.CAPTURING: 15,
    Stage.ANALYZING: 45,
    Stage.AWAITING_REVIEW: 70,
    Stage.COMMITTING: 90,
    Stage.SAVED: 100,
}

# Human-readable headline per stage (the tooltip detail carries the specifics).
_TITLE: dict[Stage, str] = {
    Stage.CAPTURING: "Reading your selection…",
    Stage.ANALYZING: "Organizing with local AI…",
    Stage.AWAITING_REVIEW: "Ready — review the note",
    Stage.COMMITTING: "Saving to your vault…",
    Stage.SAVED: "Saved ✓",
    Stage.DISCARDED: "Discarded",
    Stage.EMPTY: "Nothing was selected",
    Stage.FAILED: "Capture failed",
    Stage.PROJECTION_FAILED: "Saved (plan refresh failed)",
    Stage.REJECTED_BUSY: "Busy — finish the current review first",
    Stage.IDLE: "Ready",
}

_BUSY_STAGES = frozenset({Stage.CAPTURING, Stage.ANALYZING, Stage.COMMITTING})
_TERMINAL_STAGES = frozenset(
    {
        Stage.SAVED,
        Stage.DISCARDED,
        Stage.EMPTY,
        Stage.FAILED,
        Stage.PROJECTION_FAILED,
        Stage.REJECTED_BUSY,
    }
)
_FAIL_STAGES = frozenset({Stage.FAILED})


def progress_for(status: CaptureStatus) -> ProgressView:
    """Map one CaptureStatus to the ProgressView the popup should render."""
    stage = status.stage
    busy = stage in _BUSY_STAGES
    terminal = stage in _TERMINAL_STAGES
    if stage in _PERCENT:
        percent = _PERCENT[stage]
    elif terminal:
        percent = 100
    elif busy:
        percent = -1
    else:
        percent = 0
    return ProgressView(
        title=_TITLE.get(stage, stage.value),
        detail=status.detail,
        percent=percent,
        busy=busy,
        visible=stage is not Stage.IDLE,
        terminal=terminal,
        ok=stage not in _FAIL_STAGES,
        queued=status.pending,
    )
