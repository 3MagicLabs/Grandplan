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

import signal
import threading
from dataclasses import dataclass, field
from pathlib import Path

from grandplan.adapters.capture import make_windows_capturer, run_hotkey_listener
from grandplan.adapters.llm_contextual_reconciler import LlmContextualReconciler
from grandplan.adapters.llm_placer import LlmPlacer
from grandplan.adapters.ollama_organizer import DEFAULT_MODEL, OllamaOrganizer
from grandplan.adapters.st_embedder import SentenceTransformerEmbedder
from grandplan.app.coordinator import (
    CaptureCoordinator,
    CaptureStatus,
    Committed,
    Stage,
    committed_note_id,
)
from grandplan.app.progress import ProgressView, progress_for
from grandplan.app.review import ReviewState
from grandplan.core.edit_detect import EditDetector, HeuristicEditDetector
from grandplan.core.embed import HashingEmbedder
from grandplan.core.index_location import migrate_legacy_index
from grandplan.core.models import Source
from grandplan.core.note_store import JsonlNoteRepository
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.placement import HeuristicPlacer, Placer
from grandplan.core.ports import Embedder, Organizer
from grandplan.core.project import write_projections
from grandplan.core.reconcile import Reconciler, SimilarityReconciler
from grandplan.core.store import JsonlOriginalStore
from grandplan.core.update_detect import HeuristicUpdateDetector, UpdateDetector
from grandplan.core.vault import MarkdownVaultWriter

# Ctrl+Shift+Space avoids Ctrl+Alt (= AltGr on Windows, which fires while typing). Pass --hotkey-combo
# to override (e.g. "copilot" for the dedicated Windows Copilot key). resolve_hotkey() normalizes it.
_DEFAULT_HOTKEY = "ctrl+shift+space"

# Stages worth a tray notification (the rest — incl. DISCARDED and REJECTED_BUSY, which follow a
# user action they already know about — only update the tooltip, to avoid notification spam).
_NOTIFY_STAGES = frozenset({Stage.SAVED, Stage.EMPTY, Stage.FAILED, Stage.PROJECTION_FAILED})


def _clip(text: str, limit: int) -> str:
    """Bound a progress-popup label so a long title/detail can't blow the popup off-screen.

    Collapses whitespace (so newlines don't make the popup tall) and ellipsises past `limit` chars.
    Pure + tested even though the Qt popup that uses it is `pragma: no cover`.
    """
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"


@dataclass(eq=False)  # identity-keyed: tracked in a set, and has a mutable `approved` (not frozen)
class _ReviewRequest:
    """A worker-thread request for a main-thread review decision; the worker waits on `event`."""

    state: ReviewState
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


def run_app(  # pragma: no cover - Qt GUI; needs Windows + grandplan[windows,gui]
    *,
    vault_dir: Path,
    hotkey: str = _DEFAULT_HOTKEY,
    use_llm: bool = True,
    use_embeddings: bool = False,
    model: str = DEFAULT_MODEL,
) -> int:
    from PySide6 import QtCore, QtWidgets

    # PR-F (RC1): the local model is the default and is REQUIRED when selected — a missing/unreachable
    # model raises `OrganizerUnavailable`, which the coordinator surfaces as a FAILED status while the
    # verbatim capture stays in the inbox (organize runs after the original is persisted). No silent
    # keyword garbage. `--no-llm` selects the deterministic baseline deliberately.
    organizer: Organizer = (
        OllamaOrganizer(model=model, require=True) if use_llm else HeuristicOrganizer()
    )
    embedder: Embedder = SentenceTransformerEmbedder() if use_embeddings else HashingEmbedder()
    # Under --llm, the LLM reconciles a new capture against the WHOLE most-similar neighborhood in
    # one call (sees each related note's content + status) → richer typed links
    # (builds_on/refines/supersedes/contradicts/duplicate); without it, the cosine baseline.
    reconciler: Reconciler = (
        LlmContextualReconciler(model=model) if use_llm else SimilarityReconciler()
    )
    # Update/edit intent detection is ALWAYS the deterministic, cue-based heuristic — never the LLM,
    # even under --llm. The LLM detector hallucinated update-intent on genuinely-new ideas (e.g. a new
    # AI note read as a "next" status update to a related one), so a distinct idea got silently
    # collapsed into an existing note instead of becoming its own. Captures must never be lost: a new
    # idea only becomes an update when the text carries an EXPLICIT progress cue ("done: …", "up next:
    # …", "started …"); otherwise it's a new note (which the reconciler then LINKS to related ones).
    # The LLM is still used for the valuable work — organize, placement, relationship classification.
    detector: UpdateDetector = HeuristicUpdateDetector()
    edit_detector: EditDetector = HeuristicEditDetector()
    # PR-G: place each new note into the graph's structure (part_of parent + depends_on prereqs) so
    # the plan/masterplan get real hierarchy and sequence — not just similarity links. LLM proposes
    # parent + dependencies under --llm (heuristic fallback); the heuristic baseline does part_of.
    placer: Placer = LlmPlacer(model=model) if use_llm else HeuristicPlacer()
    # Persistent index: rehydrates prior notes/embeddings/edges so a new capture links against
    # the whole vault history, not just this session (SPEC US-5). Kept OUTSIDE the vault so a
    # cloud sync (OneDrive/Dropbox) can't churn/conflict the internal index; migrates any legacy
    # in-vault `.grandplan/` out, once.
    index_root = migrate_legacy_index(vault_dir)
    repo = JsonlNoteRepository(index_root / "index.jsonl")
    originals = JsonlOriginalStore(index_root / "inbox.jsonl")
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

    class _ProgressPopup(QtWidgets.QWidget):
        """A small frameless, always-on-top popup that shows the live capture stage + a progress bar.

        Renders a pure `ProgressView` (app.progress) so the user always sees what's happening after
        hitting the hotkey; auto-hides shortly after a terminal stage (saved / discarded / failed)."""

        def __init__(self) -> None:
            super().__init__(
                None,
                QtCore.Qt.WindowType.FramelessWindowHint
                | QtCore.Qt.WindowType.WindowStaysOnTopHint
                | QtCore.Qt.WindowType.Tool,
            )
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setFixedWidth(340)
            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(14, 12, 14, 12)
            self._title = QtWidgets.QLabel("grandplan")
            self._title.setStyleSheet("font-weight: 600; font-size: 13px;")
            self._title.setWordWrap(
                True
            )  # wrap a long title within the fixed width, never widen it
            self._detail = QtWidgets.QLabel("")
            self._detail.setWordWrap(True)
            self._detail.setStyleSheet("color: palette(mid);")
            self._bar = QtWidgets.QProgressBar()
            self._bar.setTextVisible(False)
            self._bar.setFixedHeight(8)
            layout.addWidget(self._title)
            layout.addWidget(self._detail)
            layout.addWidget(self._bar)
            self._hide_timer = QtCore.QTimer(self)
            self._hide_timer.setSingleShot(True)
            self._hide_timer.timeout.connect(self.hide)

        def _move_to_corner(self) -> None:
            screen = QtWidgets.QApplication.primaryScreen()
            if screen is None:
                return
            self.adjustSize()
            area = screen.availableGeometry()
            self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)

        def render_view(self, view: ProgressView) -> None:
            if not view.visible:
                self.hide()
                return
            self._hide_timer.stop()
            self._title.setText(_clip(view.title, 90))  # keep the popup compact + on-screen
            self._detail.setText(_clip(view.detail, 140))
            if view.percent < 0:
                self._bar.setRange(0, 0)  # indeterminate — working, unknown ETA
            else:
                self._bar.setRange(0, 100)
                self._bar.setValue(view.percent)
            colour = "#d33" if not view.ok else ("#3a3" if view.terminal else "#39f")
            self._bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {colour}; }}")
            self._move_to_corner()
            self.show()
            self.raise_()
            if view.terminal:
                self._hide_timer.start(2500)  # linger briefly so the outcome is readable

    progress_popup = _ProgressPopup()

    def _on_review_requested(request: _ReviewRequest) -> None:
        request.approved = _show_review(request.state)
        request.event.set()  # unblock the worker waiting for the decision

    def _on_status_changed(status: CaptureStatus) -> None:
        tray.setToolTip(f"grandplan — {status.detail or status.stage.value}")
        progress_popup.render_view(progress_for(status))  # the always-visible live progress popup
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

    def reproject(result: Committed) -> None:
        # Refresh the plan + graph AND re-render the note files from derived state, so a status
        # update / edit shows up everywhere (a `done` capture leaves "Now"; an edit updates the
        # note's title/body/due + its History section). Runs on the worker thread (PR-B/PR-C).
        # reconcile_deletions: a note whose .md the user deleted in Obsidian is tombstoned (not
        # resurrected); protect the just-committed note so it isn't mistaken for a deletion.
        # Protect the just-touched note (new OR the target of a status update / edit) so the
        # deletion-reconciler never mistakes it for a note the user removed in Obsidian.
        protect = frozenset({committed_note_id(result)})
        write_projections(
            repo, vault_dir, originals=originals, reconcile_deletions=True, protect_ids=protect
        )

    coordinator = CaptureCoordinator(
        capturer=make_windows_capturer(),
        organizer=organizer,
        embedder=embedder,
        reconciler=reconciler,
        repo=repo,
        originals=originals,
        vault=vault,
        review=review,
        source=Source(app="grandplan", title="capture"),
        on_status=bridge.status_changed.emit,
        after_commit=reproject,
        detector=detector,
        edit_detector=edit_detector,
        placer=placer,
    )

    def quit_app() -> None:
        # Release any worker blocked waiting for a review decision (approved stays False = discard),
        # then ask the Qt loop to exit. The actual worker shutdown (coordinator.stop) runs AFTER
        # exec() returns, so clicking Quit closes the UI immediately instead of freezing on an
        # in-flight capture's join (the worker is a daemon, so the process exits regardless).
        for request in list(pending_reviews):
            request.event.set()
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

    # Make Ctrl+C / Ctrl+Break / SIGTERM quit cleanly. Qt's C++ event loop otherwise swallows the
    # signal — Python never gets the CPU to run its handler. Register a handler that asks the app to
    # quit, plus a periodic no-op QTimer that hands control back to Python ~5×/sec so the pending
    # signal is actually delivered (the standard PySide Ctrl+C fix).
    for _signame in ("SIGINT", "SIGBREAK", "SIGTERM"):
        _signum = getattr(signal, _signame, None)
        if _signum is not None:
            try:
                signal.signal(_signum, lambda *_: quit_app())
            except (ValueError, OSError):  # not the main thread / unsupported here — skip
                pass
    _sig_pump = QtCore.QTimer()
    _sig_pump.start(200)
    _sig_pump.timeout.connect(lambda: None)

    try:
        return int(app.exec())
    finally:
        # Final cleanup once the UI is gone — release any waiter and stop the worker. Off the UI
        # path, so quitting is never blocked by an in-flight capture.
        for request in list(pending_reviews):
            request.event.set()
        coordinator.stop()


def _show_review(state: ReviewState) -> bool:  # pragma: no cover - Qt dialog
    from PySide6 import QtWidgets

    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("grandplan — review capture")
    layout = QtWidgets.QVBoxLayout(dialog)
    if state.is_status_update:
        # PR-B: this capture is a progress update — approving marks the matched note, not a new note.
        layout.addWidget(
            QtWidgets.QLabel(
                f"<b>Update</b>: mark “{state.update_target_title}” as "
                f"<b>{state.update_status}</b> (no new note will be created)."
            )
        )
    if state.is_edit:
        # PR-C: this capture is a detail edit — approving edits the matched note's fields in place.
        layout.addWidget(
            QtWidgets.QLabel(
                f"<b>Edit</b> “{state.edit_target_title}”: <b>{state.edit_summary}</b> "
                "(no new note will be created)."
            )
        )
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
    if state.proposed_updates:
        updates = ", ".join(f"“{title}” → {status}" for title, status in state.proposed_updates)
        label = QtWidgets.QLabel("Also updating on save: " + updates)
        label.setWordWrap(True)
        layout.addWidget(label)
    layout.addWidget(QtWidgets.QLabel("Original (preserved verbatim):"))
    original = QtWidgets.QPlainTextEdit(state.original_text)
    original.setReadOnly(True)
    layout.addWidget(original)
    buttons = QtWidgets.QDialogButtonBox()
    save_btn = buttons.addButton(QtWidgets.QDialogButtonBox.StandardButton.Save)
    discard_btn = buttons.addButton(QtWidgets.QDialogButtonBox.StandardButton.Discard)
    # Wire each button's own `clicked` signal. We must NOT rely on QDialogButtonBox.rejected here:
    # Discard carries Qt's *DestructiveRole*, which never fires `rejected` (only RejectRole buttons
    # like Cancel do) — so the previous `buttons.rejected.connect(...)` left Discard completely dead.
    save_btn.clicked.connect(dialog.accept)
    discard_btn.clicked.connect(dialog.reject)
    layout.addWidget(buttons)
    return bool(dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted)
