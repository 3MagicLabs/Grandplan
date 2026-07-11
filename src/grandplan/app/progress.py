"""Pure mapping from a capture Stage to a visual ProgressView (message, %, busy, terminal).

Kept out of the Qt layer so the "what should the progress popup show" logic is fully unit-tested
(CS130 testability: controllability + observability); the GUI widget is a thin renderer of
ProgressView. Each capture moves CAPTURING → ANALYZING → AWAITING_REVIEW → COMMITTING → SAVED, with
EMPTY / DISCARDED / FAILED as terminal outcomes — so the user always sees what is happening.
"""

from __future__ import annotations

from dataclasses import dataclass

from grandplan.app.coordinator import CaptureStatus, ItemState, QueueItem, Stage


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
    Stage.ENRICHED: "Ready",
    Stage.QUEUED: "Queued",
}

_BUSY_STAGES = frozenset({Stage.CAPTURING, Stage.ANALYZING, Stage.COMMITTING})
# Routine housekeeping stays tray-only (tooltip refresh) — these must never raise the popup.
# QUEUED drives the live queue view, not the single-note popup (which stays on the in-flight note).
_HIDDEN_STAGES = frozenset({Stage.IDLE, Stage.ENRICHED, Stage.QUEUED})
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
        visible=stage not in _HIDDEN_STAGES,
        terminal=terminal,
        ok=stage not in _FAIL_STAGES,
        queued=status.pending,
    )


# -- live queue view rows (US-7 "carousel") -------------------------------------------------------
#
# The queue view renders each capture in the line as a row. Deriving the row's icon, status line,
# bar, and per-step states is pure so it's unit-tested here; the Qt widget is a dumb renderer.

# The stages a note visibly walks in the queue view's step strip (capture ▸ … ▸ save).
PIPELINE_STAGES: tuple[Stage, ...] = (
    Stage.CAPTURING,
    Stage.ANALYZING,
    Stage.AWAITING_REVIEW,
    Stage.COMMITTING,
    Stage.SAVED,
)
_STEP_LABELS: dict[Stage, str] = {
    Stage.CAPTURING: "capture",
    Stage.ANALYZING: "analyze",
    Stage.AWAITING_REVIEW: "review",
    Stage.COMMITTING: "commit",
    Stage.SAVED: "save",
}
_SECTION: dict[ItemState, str] = {
    ItemState.IN_FLIGHT: "now",
    ItemState.QUEUED: "queued",
    ItemState.SAVED: "done",
    ItemState.DISCARDED: "done",
    ItemState.FAILED: "done",
    ItemState.EMPTY: "done",
}
_DONE_LINE: dict[ItemState, str] = {
    ItemState.SAVED: "saved ✓",
    ItemState.DISCARDED: "discarded",
    ItemState.FAILED: "failed",
    ItemState.EMPTY: "empty",
}


@dataclass(frozen=True)
class QueueRowView:
    """Everything the queue view needs to render one capture's row (pure; Qt-free)."""

    icon: str  # 📱 phone / 🖥️ desktop, from the note's Source.app
    snippet: str  # one-line preview of the captured text
    line: str  # status line: a stage headline / "#N in line" / "saved ✓"
    percent: int  # bar fill 0..100, or -1 = indeterminate (actively working)
    section: str  # "now" | "queued" | "done" — which band of the pipeline it sits in
    ok: bool  # False only for a failed capture (row tinted red)
    steps: tuple[tuple[str, str], ...]  # (label, "done"|"active"|"todo") — in-flight rows only


def _icon_for(source: str) -> str:
    return "📱" if "phone" in source.lower() else "🖥️"


def _steps_for(stage: Stage | None) -> tuple[tuple[str, str], ...]:
    """The step strip with each stage marked done / active / todo relative to the current one."""
    current = PIPELINE_STAGES.index(stage) if stage in PIPELINE_STAGES else -1
    steps = []
    for index, pipeline_stage in enumerate(PIPELINE_STAGES):
        if current >= 0 and index < current:
            state = "done"
        elif index == current:
            state = "active"
        else:
            state = "todo"
        steps.append((_STEP_LABELS[pipeline_stage], state))
    return tuple(steps)


def row_for(item: QueueItem) -> QueueRowView:
    """Map one QueueItem snapshot to its renderable row."""
    section = _SECTION.get(item.state, "done")
    if item.state is ItemState.IN_FLIGHT:
        stage = item.stage
        if stage is None:  # in flight but no stage emitted yet
            line, percent = "Working…", -1
        else:
            line = _TITLE.get(stage, "Working…")
            # Busy stages animate (indeterminate); AWAITING_REVIEW rests at a determinate 70%.
            percent = -1 if stage in _BUSY_STAGES else _PERCENT.get(stage, -1)
        return QueueRowView(
            icon=_icon_for(item.source),
            snippet=item.snippet or "…",
            line=line,
            percent=percent,
            section=section,
            ok=True,
            steps=_steps_for(stage),
        )
    if item.state is ItemState.QUEUED:
        return QueueRowView(
            icon=_icon_for(item.source),
            snippet=item.snippet or "…",
            line=f"#{item.position} in line",
            percent=0,
            section=section,
            ok=True,
            steps=(),
        )
    return QueueRowView(  # a finished note in the fading history band
        icon=_icon_for(item.source),
        snippet=item.snippet or "…",
        line=_DONE_LINE.get(item.state, "done"),
        percent=100 if item.state is ItemState.SAVED else 0,
        section=section,
        ok=item.state is not ItemState.FAILED,
        steps=(),
    )
