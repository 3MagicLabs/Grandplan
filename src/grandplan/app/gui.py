"""PySide6 tray GUI + app wiring (issue #7) — SCAFFOLD; verify on Windows.

A system-tray app: a global hotkey (or the tray's "Capture now") grabs the current selection and
hands it to a `CaptureCoordinator` (ADR-0006), which runs the capture → organize → embed →
reconcile → review → commit pipeline **on a single background worker** and reports progress.

Threading model (why this is safe and responsive):
- The global-hotkey listener and the tray menu only ever call `coordinator.submit()` — thread-safe,
  non-blocking, and **bounded**: at most one capture runs and one waits; extra presses are refused
  with a visible "busy" notification instead of stacking heavy LLM/embedding work (which used to
  exhaust memory) or being silently dropped.
- All heavy work runs on the coordinator's worker thread, so the UI never freezes.
- The only main-thread steps are the modal review dialog and tray updates; the worker marshals to
  the main thread via Qt signals (a `BlockingQueuedConnection`-style handoff using an Event), so no
  Qt object is ever touched off the main thread.

The Qt/pynput code here is lazily imported and `pragma: no cover`; the coordinator it binds to is
fully unit-tested (`tests/test_coordinator.py`) on any platform.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from grandplan.adapters.capture import make_windows_capturer, run_hotkey_listener
from grandplan.adapters.ollama_organizer import DEFAULT_MODEL, OllamaOrganizer
from grandplan.adapters.st_embedder import SentenceTransformerEmbedder
from grandplan.app.coordinator import CaptureCoordinator, CaptureStatus, Stage
from grandplan.app.review import ReviewState
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Source
from grandplan.core.note_store import JsonlNoteRepository
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.pipeline import CaptureResult
from grandplan.core.ports import Embedder, Organizer
from grandplan.core.project import write_projections
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.store import JsonlOriginalStore
from grandplan.core.vault import MarkdownVaultWriter

_DEFAULT_HOTKEY = "<ctrl>+<alt>+g"

# Stages worth a tray notification (the rest — incl. DISCARDED and REJECTED_BUSY, which follow a
# user action they already know about — only update the tooltip, to avoid notification spam).
_NOTIFY_STAGES = frozenset({Stage.SAVED, Stage.EMPTY, Stage.FAILED, Stage.PROJECTION_FAILED})


@dataclass
class _ReviewRequest:
    """A worker-thread request for a main-thread review decision; the worker waits on `event`."""

    state: ReviewState
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


def run_app(  # pragma: no cover - Qt GUI; needs Windows + grandplan[windows,gui]
    *,
    vault_dir: Path,
    hotkey: str = _DEFAULT_HOTKEY,
    use_llm: bool = False,
    use_embeddings: bool = False,
    model: str = DEFAULT_MODEL,
) -> int:
    from PySide6 import QtCore, QtWidgets

    organizer: Organizer = OllamaOrganizer(model=model) if use_llm else HeuristicOrganizer()
    embedder: Embedder = SentenceTransformerEmbedder() if use_embeddings else HashingEmbedder()
    # Persistent index: rehydrates prior notes/embeddings/edges so a new capture links against
    # the whole vault history, not just this session (SPEC US-5).
    repo = JsonlNoteRepository(vault_dir / ".grandplan" / "index.jsonl")
    originals = JsonlOriginalStore(vault_dir / ".grandplan" / "inbox.jsonl")
    vault = MarkdownVaultWriter(vault_dir)

    app = QtWidgets.QApplication.instance()
    if not isinstance(app, QtWidgets.QApplication):
        app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)

    icon = app.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxInformation)
    tray = QtWidgets.QSystemTrayIcon(icon, app)
    tray.setToolTip("grandplan — ready")

    # Bridge worker-thread events to the main (GUI) thread. Signals emitted from the worker are
    # delivered on the main thread's event loop (Qt queued connection), so widgets stay main-thread.
    class _Bridge(QtCore.QObject):
        review_requested = QtCore.Signal(object)  # _ReviewRequest
        status_changed = QtCore.Signal(object)  # CaptureStatus

    bridge = _Bridge()

    def _on_review_requested(request: _ReviewRequest) -> None:
        request.approved = _show_review(request.state)
        request.event.set()  # unblock the worker waiting for the decision

    def _on_status_changed(status: CaptureStatus) -> None:
        tray.setToolTip(f"grandplan — {status.detail or status.stage.value}")
        if status.stage in _NOTIFY_STAGES:
            tray.showMessage("grandplan", status.detail or status.stage.value)

    bridge.review_requested.connect(_on_review_requested)
    bridge.status_changed.connect(_on_status_changed)

    # Tracks reviews the worker is blocked on, so quit can release them instead of hanging.
    pending_reviews: set[_ReviewRequest] = set()

    def review(state: ReviewState) -> bool:
        """Called on the worker thread: ask the main thread to show the dialog, then block."""
        request = _ReviewRequest(state=state)
        pending_reviews.add(request)
        try:
            bridge.review_requested.emit(request)
            request.event.wait()
            return request.approved
        finally:
            pending_reviews.discard(request)

    def reproject(_result: CaptureResult) -> None:
        # Refresh the actionable plan + graph so the "grand plan" stays current (runs on the
        # worker thread, off the UI thread).
        write_projections(repo, vault_dir)

    coordinator = CaptureCoordinator(
        capturer=make_windows_capturer(),
        organizer=organizer,
        embedder=embedder,
        reconciler=SimilarityReconciler(),
        repo=repo,
        originals=originals,
        vault=vault,
        review=review,
        source=Source(app="grandplan", title="capture"),
        on_status=bridge.status_changed.emit,
        after_commit=reproject,
    )

    def quit_app() -> None:
        # Release any worker blocked waiting for a review decision (approved stays False = discard),
        # so coordinator.stop()'s join can't hang on an unanswered dialog.
        for request in list(pending_reviews):
            request.event.set()
        coordinator.stop()
        app.quit()

    menu = QtWidgets.QMenu()
    menu.addAction("Capture now", lambda: coordinator.submit())
    menu.addAction("Quit", quit_app)
    tray.setContextMenu(menu)
    tray.show()

    coordinator.start()
    threading.Thread(
        target=run_hotkey_listener,
        args=(hotkey, lambda: coordinator.submit()),
        daemon=True,
    ).start()

    return int(app.exec())


def _show_review(state: ReviewState) -> bool:  # pragma: no cover - Qt dialog
    from PySide6 import QtWidgets

    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("grandplan — review capture")
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(QtWidgets.QLabel(f"<b>{state.title}</b>  ({state.note_type})"))
    if state.is_probable_duplicate:
        layout.addWidget(QtWidgets.QLabel("⚠ Looks like a duplicate of an existing note."))
    if state.requires_review:
        layout.addWidget(
            QtWidgets.QLabel("⚠ Conflicts with an existing note — will be saved as needs-review.")
        )
    if state.links:
        summary = ", ".join(f"{relationship} {title}" for relationship, title in state.links)
        layout.addWidget(QtWidgets.QLabel("Relationships: " + summary))
    layout.addWidget(QtWidgets.QLabel("Original (preserved verbatim):"))
    original = QtWidgets.QPlainTextEdit(state.original_text)
    original.setReadOnly(True)
    layout.addWidget(original)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.StandardButton.Save
        | QtWidgets.QDialogButtonBox.StandardButton.Discard
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return bool(dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted)
