"""Live capture-queue window (US-7 "carousel") — a thin Qt renderer of the coordinator's snapshot.

The window shows every capture in the line and lets you watch each one get made in real time:
the in-flight note advancing through capture ▸ analyze ▸ review ▸ commit ▸ save, the notes queued
behind it with their place in line, and the ones just saved. It renders the pure `QueueRowView`
model (`app.progress.row_for`) — all the derivation logic is unit-tested there; this file only paints.

Vertical-pipeline layout (see docs/notes/QUEUE-VIEW-SPEC.md). The Qt code is lazily imported and
`pragma: no cover` (needs Windows + the [gui] extra); the data it renders is fully tested offline.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from grandplan.app.coordinator import QueueItem
from grandplan.app.progress import QueueRowView, row_for

# Section bands, in display order, with their headers.
_SECTIONS: tuple[tuple[str, str], ...] = (
    ("now", "Now"),
    ("queued", "In line"),
    ("done", "Recently saved"),
)
_STEP_COLOURS = {"done": "#8a8a8a", "active": "#2d7dff", "todo": "#c4c4c4"}


def _steps_html(steps: tuple[tuple[str, str], ...]) -> str:
    """The capture ▸ analyze ▸ review ▸ commit ▸ save strip, the current step bold + accented."""
    parts = []
    for label, state in steps:
        colour = _STEP_COLOURS[state]
        weight = "700" if state == "active" else "400"
        parts.append(f'<span style="color:{colour};font-weight:{weight}">{label}</span>')
    return ' <span style="color:#c4c4c4">▸</span> '.join(parts)


def build_queue_view(  # pragma: no cover - Qt shell; needs Windows + grandplan[gui]
    parent: Any = None,
) -> tuple[Any, Callable[[Sequence[QueueItem]], None]]:
    """Create the queue window; return (widget, update(items)). `update` is called on the GUI thread
    with a fresh `coordinator.queue_snapshot()` and repaints the pipeline."""
    from PySide6 import QtCore, QtWidgets

    def _row_widget(row: QueueRowView) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        box = QtWidgets.QVBoxLayout(frame)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(4)

        header = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel(row.icon)
        icon.setStyleSheet("font-size: 15px;")
        header.addWidget(icon, 0)
        snippet = QtWidgets.QLabel(row.snippet)
        snippet.setStyleSheet("font-weight: 600;")
        snippet.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        snippet.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred
        )
        header.addWidget(snippet, 1)
        status = QtWidgets.QLabel(row.line)
        status.setStyleSheet("color: %s;" % ("#d33" if not row.ok else "palette(mid)"))
        header.addWidget(status, 0, QtCore.Qt.AlignmentFlag.AlignRight)
        box.addLayout(header)

        if row.steps:
            strip = QtWidgets.QLabel(_steps_html(row.steps))
            strip.setTextFormat(QtCore.Qt.TextFormat.RichText)
            strip.setStyleSheet("font-size: 11px;")
            box.addWidget(strip)
        if row.section == "now":
            bar = QtWidgets.QProgressBar()
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            if row.percent < 0:
                bar.setRange(0, 0)  # indeterminate — actively working
            else:
                bar.setRange(0, 100)
                bar.setValue(row.percent)
            box.addWidget(bar)
        return frame

    class _QueueWindow(QtWidgets.QWidget):
        def __init__(self) -> None:
            super().__init__(parent, QtCore.Qt.WindowType.Window)
            self.setWindowTitle("grandplan — capture queue")
            self.resize(440, 520)
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            self._body = QtWidgets.QWidget()
            self._layout = QtWidgets.QVBoxLayout(self._body)
            self._layout.setContentsMargins(12, 12, 12, 12)
            self._layout.setSpacing(8)
            self._layout.addStretch(1)
            scroll.setWidget(self._body)
            outer.addWidget(scroll)

        def _clear(self) -> None:
            while self._layout.count():
                child = self._layout.takeAt(0)
                if child is None:
                    continue
                widget = child.widget()
                if widget is not None:
                    widget.deleteLater()

        def update_items(self, items: Sequence[QueueItem]) -> None:
            self._clear()
            rows = [row_for(item) for item in items]
            if not rows:
                empty = QtWidgets.QLabel("Nothing in the queue — fire a capture.")
                empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                empty.setStyleSheet("color: palette(mid); padding: 32px;")
                self._layout.addWidget(empty)
                self._layout.addStretch(1)
                return
            for _, header in _SECTIONS:
                section_rows = [r for r in rows if _header_of(r) == header]
                if not section_rows:
                    continue
                label = QtWidgets.QLabel(header.upper())
                label.setStyleSheet(
                    "color: palette(mid); font-size: 10px; font-weight: 700; letter-spacing: 1px;"
                )
                self._layout.addWidget(label)
                for row in section_rows:
                    self._layout.addWidget(_row_widget(row))
            self._layout.addStretch(1)

    def _header_of(row: QueueRowView) -> str:
        return {"now": "Now", "queued": "In line", "done": "Recently saved"}[row.section]

    window = _QueueWindow()

    def update(items: Sequence[QueueItem]) -> None:
        window.update_items(items)

    return window, update
