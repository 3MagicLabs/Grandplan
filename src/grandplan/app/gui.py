"""PySide6 tray GUI + app wiring (issue #7) — SCAFFOLD; verify on Windows.

A system-tray app: a global hotkey (or the tray's "Capture now") grabs the current selection,
runs it through the review controller (`app.review`), and shows a dialog to Save (commit) or
Discard. It binds entirely to the unit-tested view-model; the Qt/pynput code here is lazily
imported, `pragma: no cover`, and needs a Windows desktop (+ `grandplan[windows,gui]`) to run.

Threading note: the global-hotkey listener runs on a background thread and only ever puts a token
on a thread-safe queue; a Qt `QTimer` on the main thread drains it and does the capture/dialog —
so no Qt object is ever touched off the main thread.
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime, timezone
from pathlib import Path

from grandplan.adapters.capture import make_windows_capturer, run_hotkey_listener
from grandplan.adapters.ollama_organizer import OllamaOrganizer
from grandplan.adapters.st_embedder import SentenceTransformerEmbedder
from grandplan.app.review import ReviewState, approve, discard, start_review
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Source
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.ports import Embedder, Organizer
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import JsonlOriginalStore
from grandplan.core.vault import MarkdownVaultWriter

_DEFAULT_HOTKEY = "<ctrl>+<alt>+g"


def run_app(  # pragma: no cover - Qt GUI; needs Windows + grandplan[windows,gui]
    *,
    vault_dir: Path,
    hotkey: str = _DEFAULT_HOTKEY,
    use_llm: bool = False,
    use_embeddings: bool = False,
    model: str = "llama3.2:3b",
) -> int:
    from PySide6 import QtCore, QtWidgets

    organizer: Organizer = OllamaOrganizer(model=model) if use_llm else HeuristicOrganizer()
    embedder: Embedder = SentenceTransformerEmbedder() if use_embeddings else HashingEmbedder()
    reconciler = SimilarityReconciler()
    repo = InMemoryNoteRepository()
    originals = JsonlOriginalStore(vault_dir / ".grandplan" / "inbox.jsonl")
    vault = MarkdownVaultWriter(vault_dir)
    capturer = make_windows_capturer()
    triggers: queue.Queue[None] = queue.Queue()

    def do_capture() -> None:
        try:
            text = capturer.capture()
            if not text:
                return
            pending = start_review(
                text,
                created=datetime.now(timezone.utc).isoformat(),
                source=Source(app="grandplan", title="capture"),
                organizer=organizer,
                embedder=embedder,
                reconciler=reconciler,
                repo=repo,
                originals=originals,
            )
            if _show_review(pending.state):
                approve(pending, repo=repo, vault=vault)
            else:
                discard(pending)
        except Exception as exc:  # noqa: BLE001 - one failed capture must not kill the tray app
            tray.showMessage("grandplan — capture failed", str(exc))

    def drain() -> None:
        fired = False
        while not triggers.empty():
            triggers.get()
            fired = True
        if fired:
            do_capture()

    app = QtWidgets.QApplication.instance()
    if not isinstance(app, QtWidgets.QApplication):
        app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)

    icon = app.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxInformation)
    tray = QtWidgets.QSystemTrayIcon(icon, app)
    tray.setToolTip("grandplan")
    menu = QtWidgets.QMenu()
    menu.addAction("Capture now", lambda: triggers.put(None))
    menu.addAction("Quit", app.quit)
    tray.setContextMenu(menu)
    tray.show()

    poll = QtCore.QTimer()
    poll.timeout.connect(drain)
    poll.start(150)

    threading.Thread(
        target=run_hotkey_listener, args=(hotkey, lambda: triggers.put(None)), daemon=True
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
    if state.related_titles:
        layout.addWidget(QtWidgets.QLabel("Related: " + ", ".join(state.related_titles)))
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
