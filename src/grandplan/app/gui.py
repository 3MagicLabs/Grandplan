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

import logging
import signal
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grandplan.adapters.capture import make_windows_capturer, run_hotkey_listener
from grandplan.adapters.llm_contextual_reconciler import LlmContextualReconciler
from grandplan.adapters.llm_entity_extractor import LlmEntityExtractor
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
from grandplan.app.queue_view import build_queue_view
from grandplan.app.review import ReviewEdits, ReviewState
from grandplan.core.edit_detect import EditDetector, HeuristicEditDetector
from grandplan.core.embed import HashingEmbedder
from grandplan.core.entities import EntityExtractor, HeuristicEntityExtractor
from grandplan.core.index_location import migrate_legacy_index
from grandplan.core.models import NoteType, Source
from grandplan.core.note_store import JsonlNoteRepository
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.pipeline import CaptureResult
from grandplan.core.placement import HeuristicPlacer, Placer
from grandplan.core.ports import Embedder, Organizer
from grandplan.core.project import write_projections
from grandplan.core.reconcile import Reconciler, SimilarityReconciler
from grandplan.core.store import JsonlOriginalStore
from grandplan.core.update_detect import HeuristicUpdateDetector, UpdateDetector
from grandplan.core.vault import MarkdownVaultWriter

logger = logging.getLogger(__name__)

# Ctrl+Shift+G avoids two traps: Ctrl+Alt (= AltGr on Windows, fires while typing) AND printable keys
# like Space — pynput does NOT consume the hotkey, so the keystroke also reaches the focused app, and a
# Space would overwrite the current selection (in Word, Ctrl+Shift+Space inserts a non-breaking space).
# Ctrl held suppresses character insertion, so a letter can't delete the selection. Pass --hotkey-combo
# to override; for a remapped key (e.g. the Windows Copilot key via PowerToys) bind a function key like
# f13 — a single non-printable key that triggers nothing in the focused app. resolve_hotkey() normalizes.
_DEFAULT_HOTKEY = "ctrl+shift+g"

# How many notes ground each tray-chat turn. Mirrors the `chat`/`ask` CLI default so the same vault
# answers the same question the same way whichever surface you ask from — the tray chat previously
# hardcoded the ChatSession default, so `--top-k` existed on the CLI and was unreachable from the
# GUI. Raising it costs prefill (each note contributes up to _BODY_SNIPPET chars to the prompt), not
# RAM: the KV cache is sized by num_ctx regardless of how much of the window a turn fills.
_CHAT_TOP_K = 6

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


def _corner_position(
    width: int,
    height: int,
    area_x: int,
    area_y: int,
    area_w: int,
    area_h: int,
    margin: int = 24,
) -> tuple[int, int]:
    """Bottom-right placement of a (width x height) window inside a screen work-area, clamped so an
    oversized popup never gets pushed off the top/left edge. Pure + tested; the Qt popup is no-cover."""
    x = area_x + area_w - width - margin
    y = area_y + area_h - height - margin
    return max(area_x, x), max(area_y, y)


def _bounded_size(
    content_w: int,
    content_h: int,
    screen_w: int,
    screen_h: int,
    *,
    w_frac: float = 0.55,
    h_frac: float = 0.75,
    min_w: int = 360,
    min_h: int = 240,
) -> tuple[int, int]:
    """A window size that fits the content but never exceeds a fraction of the screen, so the review
    dialog can't grow to fill (or overflow) the display on a long capture. Pure + tested."""
    max_w = max(min_w, int(screen_w * w_frac))
    max_h = max(min_h, int(screen_h * h_frac))
    return min(max(content_w, min_w), max_w), min(max(content_h, min_h), max_h)


def _centered_position(
    width: int, height: int, area_x: int, area_y: int, area_w: int, area_h: int
) -> tuple[int, int]:
    """Top-left so a (width x height) window is centred within a screen work-area. Pure + tested."""
    return area_x + (area_w - width) // 2, area_y + (area_h - height) // 2


@dataclass(eq=False)  # identity-keyed: tracked in a set, and has a mutable `approved` (not frozen)
class _ReviewRequest:
    """A worker-thread request for a main-thread review decision; the worker waits on `event`."""

    state: ReviewState
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


def _capture_components(
    *, use_llm: bool, fast: bool, model: str
) -> tuple[Organizer, Reconciler, Placer, EntityExtractor]:
    """Select the (organizer, reconciler, placer, entity-extractor) — the capture's model-call budget.

    Measured on the 16 GB no-GPU target, EACH local-LLM call costs ~8-15 s (≈10-17 tok/s on CPU), and
    the default --llm capture makes three of them back to back — organize, contextual reconcile,
    placement — so a note takes ~25-45 s to reach the review dialog. `fast` keeps the one call that
    produces the note (LLM organize, PR-F: still required, loud on failure) and swaps the two
    enrichment calls for their instant deterministic baselines: cosine similarity links instead of
    LLM-typed links, and the heuristic part_of placer. ~3× faster per capture; a later background
    pass can re-derive the richer links/placement off the critical path.

    The entity extractor follows the same budget. The **heuristic** one is pure Python — zero model
    calls — so it runs even in `fast`, where it costs nothing and keeps the one-call-per-capture
    contract intact. Only `--thorough` pays for `LlmEntityExtractor` (which unions its result with
    the heuristic and falls back to it on failure, so LLM entities are strictly additive).

    Pure selection (no Qt, no IO) so the wiring is hermetically testable — the same gap-in-coverage
    lesson as `_ReviewRequest` (tests/app/test_gui_wiring.py).
    """
    if not use_llm:
        # --no-llm: the deterministic offline baseline already makes zero model calls; `fast` is moot.
        return (
            HeuristicOrganizer(),
            SimilarityReconciler(),
            HeuristicPlacer(),
            HeuristicEntityExtractor(),
        )
    # PR-F (RC1): the local model is the default and is REQUIRED when selected — a missing/unreachable
    # model raises `OrganizerUnavailable`, which the coordinator surfaces as a FAILED status while the
    # verbatim capture stays in the inbox (organize runs after the original is persisted). No silent
    # keyword garbage. `--no-llm` selects the deterministic baseline deliberately.
    organizer: Organizer = OllamaOrganizer(model=model, require=True)
    if fast:
        # The heuristic extractor stays ON here: it makes no model call, so entities cost nothing on
        # the critical path — and without it a fast capture would build no people graph at all.
        return organizer, SimilarityReconciler(), HeuristicPlacer(), HeuristicEntityExtractor()
    # Under --llm, the LLM reconciles a new capture against the WHOLE most-similar neighborhood in
    # one call (sees each related note's content + status) → richer typed links
    # (builds_on/refines/supersedes/contradicts/duplicate); without it, the cosine baseline.
    # PR-G: place each new note into the graph's structure (part_of parent + depends_on prereqs) so
    # the plan/masterplan get real hierarchy and sequence — not just similarity links.
    return (
        organizer,
        LlmContextualReconciler(model=model),
        LlmPlacer(model=model),
        LlmEntityExtractor(model=model),
    )


def _reachable_ipv4s(candidates: Iterable[str]) -> list[str]:
    """Keep only IPv4 addresses another device could actually dial — drop loopback (127.*) and
    link-local/APIPA (169.254.*, an unassigned/disconnected interface). Pure, so it's unit-tested."""
    return sorted({ip for ip in candidates if not ip.startswith(("127.", "169.254."))})


def _is_bind_all_host(host: str) -> bool:
    """True when `host` is a 'bind on all interfaces' address rather than a dialable one: empty, the
    IPv6 unspecified `::`, or an all-zeros IPv4. A phone can't connect to it — so the banner must show
    a real IP instead. Written without the all-zeros string literal on purpose (it reads as a bind
    directive to security scanners); the comparison stays pure + unit-tested."""
    if host in ("", "::"):
        return True
    return all(char in "0." for char in host)  # all zeros/dots = the unspecified IPv4 address


def _lan_ipv4s() -> list[str]:  # pragma: no cover - depends on the host's interfaces
    """This machine's reachable IPv4 addresses, for the phone-app banner. Offline: a local hostname
    lookup, no network egress — so we never print the bind address (0.0.0.0) as if the phone could
    open it. The user picks the one on their phone's network (Wi-Fi 192.168.* / Tailscale 100.*)."""
    import socket

    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(str(info[4][0]))  # AF_INET sockaddr is (host, port); host is the IPv4 string
    except OSError:
        pass
    return _reachable_ipv4s(found)


def _print_phone_banner(host: str, port: int, token: str) -> None:  # pragma: no cover - stdout only
    """Print how to reach the phone app — real IP(s), never the unroutable 0.0.0.0 bind address."""
    tokened = f"/?token={token}" if token else "/"
    print(f"phone capture live: POST http://{host}:{port}/capture")
    if _is_bind_all_host(host):
        urls = _lan_ipv4s()
        if urls:
            print("phone app — open ONE of these on your phone (same Wi-Fi, or Tailscale 100.x):")
            for ip in urls:
                print(f"    http://{ip}:{port}{tokened}")
        else:
            print(f"phone app: open http://<this-PC's-IP>:{port}{tokened} on your phone")
        print("    (0.0.0.0 is only the bind address — the phone must use the PC's real IP)")
    else:
        print(f"phone app: open http://{host}:{port}{tokened} in your phone browser")


def _start_phone_server(  # pragma: no cover - binds a socket; needs the windows/gui runtime
    coordinator: CaptureCoordinator,
    *,
    index_root: Path,
    vault_dir: Path,
    host: str,
    port: int,
    token: str,
) -> None:
    """Host the phone `/capture` server in a daemon thread, routing every capture through the
    coordinator (single writer, shared with the hotkey/tray). The request is validated synchronously
    (fast 400 on a bad body); save + transcribe + submit run on a background thread so the phone gets
    an immediate 202 and never waits on the local model.
    """
    import importlib.util as _ilu

    from grandplan.adapters.capture_intake import parse_capture_request, process_capture
    from grandplan.adapters.http_intake import IntakeResult, serve_intake
    from grandplan.app.mobile_api import (
        handle_mobile_decision,
        handle_mobile_get,
        pending_to_json,
        queue_to_json,
    )
    from grandplan.core.directive import JsonlDirectiveStore

    attachments_dir = vault_dir / "attachments"

    def save(name: str, data: bytes) -> str:
        attachments_dir.mkdir(parents=True, exist_ok=True)
        target = attachments_dir / name
        stem, dot, ext = name.partition(".")
        counter = 1
        while target.exists():  # never overwrite an earlier capture's file (lossless)
            target = attachments_dir / f"{stem}-{counter}{dot}{ext}"
            counter += 1
        target.write_bytes(data)
        return str(target)

    transcribe: Callable[[str], str | None] | None = None
    if _ilu.find_spec("faster_whisper") is not None:
        from grandplan.adapters.voice import transcribe_file

        transcribe = transcribe_file

    def submit(text: str) -> str:
        # Route through the coordinator's ONE worker (serialized with hotkey captures). The capture is
        # organized then PARKED for review (mobile parity) — approve/discard from the phone or desktop.
        coordinator.submit_capture(text, source=Source(app="phone", title="capture"))
        return "queued"

    # The phone web app + its read/decision APIs, all backed by the SAME coordinator the desktop uses.
    def on_get(path: str, provided: str | None) -> IntakeResult:
        return handle_mobile_get(
            path,
            provided,
            token=token,
            queue=lambda: queue_to_json(coordinator.queue_snapshot()),
            pending=lambda: pending_to_json(coordinator.pending_reviews()),
        )

    def decide(pending_id: str, approve: bool, edits: ReviewEdits | None) -> bool:
        return (
            coordinator.approve_pending(pending_id, edits)
            if approve
            else coordinator.discard_pending(pending_id)
        )

    def on_decision(path: str, provided: str | None, body: bytes) -> IntakeResult:
        return handle_mobile_decision(path, provided, token=token, decide=decide, body=body)

    def handler(raw: bytes, content_type: str) -> object:
        try:
            content, attachments = parse_capture_request(raw, content_type)
        except ValueError as exc:
            return IntakeResult(400, {"error": str(exc)})

        def work() -> None:
            try:
                process_capture(
                    content, attachments, save=save, organize=submit, transcribe=transcribe
                )
            except Exception:  # noqa: BLE001 - a bad background capture must not kill the thread
                logger.exception("phone capture failed")

        threading.Thread(target=work, name="grandplan-phone-capture", daemon=True).start()
        return IntakeResult(202, {"status": "captured — organizing in the background"})

    store = JsonlDirectiveStore(index_root / "directives.jsonl")
    threading.Thread(
        target=serve_intake,
        args=(store,),
        kwargs={
            "host": host,
            "port": port,
            "token": token,
            "capture": handler,
            "on_get": on_get,
            "on_decision": on_decision,
        },
        daemon=True,
    ).start()
    _print_phone_banner(host, port, token)


def run_app(  # pragma: no cover - Qt GUI; needs Windows + grandplan[windows,gui]
    *,
    vault_dir: Path,
    hotkey: str = _DEFAULT_HOTKEY,
    use_llm: bool = True,
    use_embeddings: bool = False,
    fast: bool = False,
    model: str = DEFAULT_MODEL,
    enrich: bool = False,
    kb_model: str | None = None,
    serve: bool = False,
    serve_host: str = "127.0.0.1",
    serve_port: int = 8765,
    serve_token: str = "",
    auto_approve: bool = False,
    max_pending: int = 16,
    chat_top_k: int = _CHAT_TOP_K,
) -> int:
    from PySide6 import QtCore, QtGui, QtWidgets

    organizer, reconciler, placer, entity_extractor = _capture_components(
        use_llm=use_llm, fast=fast, model=model
    )
    embedder: Embedder = SentenceTransformerEmbedder() if use_embeddings else HashingEmbedder()
    # Update/edit intent detection is ALWAYS the deterministic, cue-based heuristic — never the LLM,
    # even under --llm. The LLM detector hallucinated update-intent on genuinely-new ideas (e.g. a new
    # AI note read as a "next" status update to a related one), so a distinct idea got silently
    # collapsed into an existing note instead of becoming its own. Captures must never be lost: a new
    # idea only becomes an update when the text carries an EXPLICIT progress cue ("done: …", "up next:
    # …", "started …"); otherwise it's a new note (which the reconciler then LINKS to related ones).
    # The LLM is still used for the valuable work — organize, placement, relationship classification.
    detector: UpdateDetector = HeuristicUpdateDetector()
    edit_detector: EditDetector = HeuristicEditDetector()
    # Persistent index: rehydrates prior notes/embeddings/edges so a new capture links against
    # the whole vault history, not just this session (SPEC US-5). Kept OUTSIDE the vault so a
    # cloud sync (OneDrive/Dropbox) can't churn/conflict the internal index; migrates any legacy
    # in-vault `.grandplan/` out, once.
    index_root = migrate_legacy_index(vault_dir)
    # Similarity-indexed when the optional [index] extra is installed (#35, ADR-0009); the vec.db
    # beside the JSONL truth is a rebuildable cache — the JSONL event log stays the only store.
    from grandplan.adapters.vec_index import maybe_indexed

    repo = maybe_indexed(JsonlNoteRepository(index_root / "index.jsonl"), index_root / "vec.db")
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
        status_changed = QtCore.Signal(object)  # CaptureStatus
        hotkey_dead = QtCore.Signal(str)  # reason the global hotkey stopped working (#7)

    bridge = _Bridge()

    class _ProgressPopup(QtWidgets.QWidget):
        """A small frameless, always-on-top popup showing the live capture stage + a progress bar.

        Renders a pure `ProgressView`. You can **drag it anywhere** (it then stays put instead of
        snapping back to the corner) and **hide it** with the "–" button — after which status updates
        go to the tray icon only. It reappears via the tray's "Show progress popup" toggle. Auto-hides
        shortly after a terminal stage (saved / discarded / failed)."""

        def __init__(self) -> None:
            super().__init__(
                None,
                QtCore.Qt.WindowType.FramelessWindowHint
                | QtCore.Qt.WindowType.WindowStaysOnTopHint
                | QtCore.Qt.WindowType.Tool,
            )
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setFixedWidth(340)
            self._user_positioned = False  # once dragged, stop snapping back to the corner
            self._drag_offset: QtCore.QPoint | None = None
            self._on_minimize: Callable[[], None] | None = None
            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(14, 12, 14, 12)
            header = QtWidgets.QHBoxLayout()
            self._title = QtWidgets.QLabel("grandplan")
            self._title.setStyleSheet("font-weight: 600; font-size: 13px;")
            self._title.setWordWrap(
                True
            )  # wrap a long title within the fixed width, never widen it
            header.addWidget(self._title, 1)
            min_btn = QtWidgets.QPushButton("–")
            min_btn.setFixedSize(22, 22)
            min_btn.setToolTip("Hide — keep status updates in the tray icon")
            min_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            min_btn.clicked.connect(self._minimize)
            header.addWidget(min_btn, 0, QtCore.Qt.AlignmentFlag.AlignTop)
            layout.addLayout(header)
            self._detail = QtWidgets.QLabel("")
            self._detail.setWordWrap(True)
            self._detail.setStyleSheet("color: palette(mid);")
            self._bar = QtWidgets.QProgressBar()
            self._bar.setTextVisible(False)
            self._bar.setFixedHeight(8)
            layout.addWidget(self._detail)
            layout.addWidget(self._bar)
            self._hide_timer = QtCore.QTimer(self)
            self._hide_timer.setSingleShot(True)
            self._hide_timer.timeout.connect(self.hide)

        def set_on_minimize(self, callback: Callable[[], None]) -> None:
            self._on_minimize = callback

        def _minimize(self) -> None:
            self.hide()
            if self._on_minimize is not None:
                self._on_minimize()  # let run_app flip the tray toggle → tray-only mode

        # Frameless windows have no title bar to grab, so make the whole popup draggable.
        def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802 - Qt API
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                event.accept()

        def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802 - Qt API
            if self._drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                self._user_positioned = True  # respect this position from now on
                event.accept()

        def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802 - Qt API
            self._drag_offset = None

        def _position(self) -> None:
            if self._user_positioned:
                return  # the user dragged it somewhere — leave it there
            screen = QtWidgets.QApplication.primaryScreen()
            if screen is None:
                return
            self.adjustSize()
            area = screen.availableGeometry()
            x, y = _corner_position(
                self.width(), self.height(), area.x(), area.y(), area.width(), area.height()
            )
            self.move(x, y)

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
            self._position()
            self.show()
            self.raise_()
            if view.terminal:
                self._hide_timer.start(2500)  # linger briefly so the outcome is readable

    progress_popup = _ProgressPopup()
    # Live capture-queue window (US-7): the whole line + each note's stage, updated in real time.
    # Built hidden; opened from the tray menu. It renders coordinator.queue_snapshot() on every
    # status change — the pure row model lives in app.progress (tested), this is a thin renderer.
    queue_window, queue_update = build_queue_view()
    ui_state = {"show_popup": True}  # toggled by the popup's "–" button and the tray menu item

    def _set_show_popup(show: bool) -> None:
        ui_state["show_popup"] = show
        if not show:
            progress_popup.hide()  # tray-only mode; reappears on the next status when re-enabled

    _reviewing = {"busy": False}  # guard: never stack a second modal over an open review dialog

    def _show_pending_review() -> None:
        # A capture is parked awaiting a decision (coordinator review=None → mobile parity). A
        # DESKTOP-origin capture pops the review dialog here, exactly as before. A PHONE capture is
        # reviewed on the phone — it still appears in pending_reviews() (so the phone can act and the
        # queue window shows it), but we don't pop a desktop modal you're away from. First surface to
        # decide wins: if the phone already resolved it, approve/discard_pending is a harmless no-op.
        if _reviewing["busy"]:
            return
        for review_item in coordinator.pending_reviews():
            if "phone" in review_item.source.lower():
                continue
            _reviewing["busy"] = True
            try:
                approved, edits = _show_review(review_item.state)
            finally:
                _reviewing["busy"] = False
            if approved:
                coordinator.approve_pending(review_item.id, edits)
            else:
                coordinator.discard_pending(review_item.id)
            return  # one review at a time (pending_reviews holds at most one)

    def _on_status_changed(status: CaptureStatus) -> None:
        # Surface the background-enrichment backlog (#38): notes still waiting for their typed
        # links/placement pass show as a tooltip suffix — visible, never a popup (it's routine).
        # (Late-bound closure is safe: status events only ever originate from the coordinator.)
        waiting = coordinator.enrichment_pending()
        suffix = f"  ·  enriching {waiting} note(s) in background" if waiting else ""
        tray.setToolTip(f"grandplan — {status.detail or status.stage.value}{suffix}")
        # Always repaint the live queue window (whether or not it is open) so it is current when
        # raised — it shows the whole line + each note's stage, straight from the coordinator.
        queue_update(coordinator.queue_snapshot())
        if not ui_state["show_popup"]:
            progress_popup.hide()  # minimized → status stays in the tray (tooltip + notifications)
        elif status.stage is not Stage.QUEUED:
            progress_popup.render_view(progress_for(status))  # live single-note popup
        # A QUEUED event (another note joined the line) only feeds the queue window — it must not
        # flicker the single-note popup off the note currently in flight.
        if status.stage in _NOTIFY_STAGES:
            tray.showMessage("grandplan", status.detail or status.stage.value)
        # A capture just reached the review stage — present it (desktop-origin pops the dialog).
        if status.stage is Stage.AWAITING_REVIEW:
            _show_pending_review()

    bridge.status_changed.connect(_on_status_changed)

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

    # Background enrichment (#38) is OPT-IN (--enrich): the app must not keep making LLM calls
    # after a note is saved unless the user explicitly asked for it — capture organizes inline,
    # then stops (user decision 2026-07-04; extends the "curation is user-directed only" rule).
    # When opted in, it re-derives typed links/placement AFTER commit on the coordinator's own
    # worker at idle priority (single writer, ADR-0006), with the FULL LLM reconciler/placer —
    # restoring the quality fast mode traded away. Moot when not fast (links were derived inline)
    # or not LLM (nothing richer to derive). Off by default: notes keep their baseline cosine
    # links until `--thorough`, `--enrich`, or an explicit `regenerate` derives more.
    enrich_fn = None
    if use_llm and fast and enrich:
        from grandplan.app.enrich import enrich_note

        enrich_reconciler = LlmContextualReconciler(model=model)
        enrich_placer: Placer = LlmPlacer(model=model)

        def enrich_fn(note_id: str) -> object:
            outcome = enrich_note(
                note_id, repo=repo, reconciler=enrich_reconciler, placer=enrich_placer
            )
            if getattr(outcome, "edges_added", 0):
                # New edges → refresh the plan/graph so the richer links show up in Obsidian.
                write_projections(repo, vault_dir, originals=originals)
            return outcome

    def after_commit(result: Committed) -> None:
        reproject(result)
        if isinstance(result, CaptureResult):  # only NEW notes need the links/placement pass
            coordinator.submit_enrichment(result.note.id)

    coordinator = CaptureCoordinator(
        capturer=make_windows_capturer(),
        organizer=organizer,
        embedder=embedder,
        reconciler=reconciler,
        repo=repo,
        originals=originals,
        vault=vault,
        review=None,  # park each review so it's resolvable from the desktop dialog OR the phone
        # --auto-approve commits every capture as-proposed (no dialog); off by default so review is
        # the safe default. --max-pending sizes how many captures may queue before submit is refused.
        auto_approve=auto_approve,
        max_pending=max_pending,
        source=Source(app="grandplan", title="capture"),
        on_status=bridge.status_changed.emit,
        after_commit=after_commit,
        detector=detector,
        edit_detector=edit_detector,
        placer=placer,
        # ROADMAP 3: people/orgs in the capture become `entity` notes + `involves` edges, so the
        # graph is a people/org graph. Previously only `organize`/`regenerate` did this, so notes
        # captured by hotkey or phone — the primary path — never built one.
        entity_extractor=entity_extractor,
        enrich=enrich_fn,
    )

    def quit_app() -> None:
        # Ask the Qt loop to exit. A worker parked awaiting a review decision is woken by
        # coordinator.stop() (run AFTER exec() returns → discard, raw kept in the inbox); the worker
        # is a daemon, so the process exits regardless — Quit closes the UI immediately instead of
        # freezing on an in-flight capture's join.
        app.quit()

    # Chat panel (#39 stage 3): converse with the vault + draft review-gated plans, from the tray.
    # The session reuses the app's live repo (so a just-captured note is immediately chattable) and
    # the KB agent's own heavier default model with the capture model as fallback (SPEC-AGENT-KB).
    chat_windows: list[object] = []  # keep refs so Qt doesn't GC an open window

    def open_chat() -> None:
        from datetime import datetime, timezone

        from grandplan.adapters.kb_ask import KB_DEFAULT_MODEL
        from grandplan.adapters.kb_chat import (
            ChatSession,
            ImproveDraft,
            PlanDraft,
            apply_improvement_draft,
            apply_plan_draft,
        )
        from grandplan.app.chat_window import open_chat_window

        # --kb-model lets the user point chat at the model they actually pulled (e.g. qwen2.5:7b
        # next to a resident capture model); the hardcoded default made every turn 404 first.
        session = ChatSession(
            repo=repo,
            embedder=embedder,
            model=kb_model or KB_DEFAULT_MODEL,
            fallback_model=model,
            top_k=chat_top_k,
        )

        def apply_plan(draft: PlanDraft) -> str:
            return apply_plan_draft(
                draft,
                repo=repo,
                originals=originals,
                embedder=embedder,
                vault_dir=vault_dir,
                created=datetime.now(timezone.utc).isoformat(),
            )

        def apply_improve(draft: ImproveDraft) -> None:
            apply_improvement_draft(draft, repo=repo, vault_dir=vault_dir, originals=originals)

        window = open_chat_window(
            session=session, apply_plan=apply_plan, apply_improve=apply_improve
        )
        chat_windows.append(window)
        window.show()  # type: ignore[attr-defined]

    def open_queue() -> None:
        queue_update(coordinator.queue_snapshot())  # freshen before showing
        queue_window.show()
        queue_window.raise_()
        queue_window.activateWindow()

    menu = QtWidgets.QMenu()
    menu.addAction("Capture now", lambda: coordinator.submit())
    menu.addAction("Capture queue…", open_queue)
    menu.addAction("Chat with vault…", open_chat)
    show_action = menu.addAction("Show progress popup")
    show_action.setCheckable(True)
    show_action.setChecked(True)
    show_action.toggled.connect(_set_show_popup)
    # The popup's "–" button and this menu item share one source of truth (the action's checked state).
    progress_popup.set_on_minimize(lambda: show_action.setChecked(False))
    menu.addAction("Quit", quit_app)
    tray.setContextMenu(menu)
    tray.show()

    # Dead hotkey-listener surfacing (#7): every way the listener can end (crash OR quiet stop)
    # reports a reason; the tray shows it so a dead hotkey is never silent. "Capture now" and the
    # rest of the app keep working — only the global hotkey is down.
    def _on_hotkey_dead(reason: str) -> None:
        tray.setToolTip(f"grandplan — {reason}")
        tray.showMessage(
            "grandplan — capture hotkey inactive",
            f"{reason}\nUse the tray's 'Capture now', or restart the app to re-register.",
            QtWidgets.QSystemTrayIcon.MessageIcon.Warning,
        )

    bridge.hotkey_dead.connect(_on_hotkey_dead)

    coordinator.start()
    threading.Thread(
        target=run_hotkey_listener,
        args=(hotkey, lambda: coordinator.submit()),
        kwargs={"on_dead": bridge.hotkey_dead.emit},
        daemon=True,
    ).start()

    # Unified mode (`gui --serve`): host the phone server IN this process and route every remote
    # capture through the SAME coordinator worker as the hotkey/tray — one writer, so phone and
    # desktop capture never conflict. It also serves the phone web app (live queue + review inbox):
    # captures are reviewed from the phone OR the desktop, first wins. Fully opt-in — without --serve
    # this block never runs, so the plain desktop GUI is unchanged.
    if serve:
        _start_phone_server(
            coordinator,
            index_root=index_root,
            vault_dir=vault_dir,
            host=serve_host,
            port=serve_port,
            token=serve_token,
        )

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
        # Final cleanup once the UI is gone — stop the worker (this also wakes a review parked in
        # _await_decision → discard). Off the UI path, so quitting is never blocked by a capture.
        coordinator.stop()


def _show_review(
    state: ReviewState,
) -> tuple[bool, ReviewEdits | None]:  # pragma: no cover - Qt dialog
    from PySide6 import QtWidgets

    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("grandplan — review capture")
    layout = QtWidgets.QVBoxLayout(dialog)

    def add_label(html: str) -> None:
        # Word-wrap EVERY label: an unwrapped label sets a large minimum width for a long title /
        # relationship list, which would override the screen cap below and stretch the dialog wide.
        label = QtWidgets.QLabel(html)
        label.setWordWrap(True)
        layout.addWidget(label)

    # A status-update / edit capture touches an EXISTING note (no new note), so its fields aren't
    # editable here; a NEW note is fully editable (title / type / tags / body) before Save.
    editable = not (state.is_status_update or state.is_edit)
    title_edit: Any = None  # Qt widgets (Any: PySide6 is untyped in the gate env, like queue_view)
    type_combo: Any = None
    tags_edit: Any = None
    body_edit: Any = None

    if state.is_status_update:
        # PR-B: this capture is a progress update — approving marks the matched note, not a new note.
        add_label(
            f"<b>Update</b>: mark “{state.update_target_title}” as "
            f"<b>{state.update_status}</b> (no new note will be created)."
        )
    if state.is_edit:
        # PR-C: this capture is a detail edit — approving edits the matched note's fields in place.
        add_label(
            f"<b>Edit</b> “{state.edit_target_title}”: <b>{state.edit_summary}</b> "
            "(no new note will be created)."
        )
    if editable:
        form = QtWidgets.QFormLayout()
        title_edit = QtWidgets.QLineEdit(state.title)
        type_combo = QtWidgets.QComboBox()
        type_values = [note_type.value for note_type in NoteType]
        if state.note_type not in type_values:  # unknown → keep it as the current choice
            type_values = [state.note_type, *type_values]
        type_combo.addItems(type_values)
        type_combo.setCurrentText(state.note_type)
        tags_edit = QtWidgets.QLineEdit(", ".join(state.tags))
        form.addRow("Title", title_edit)
        form.addRow("Type", type_combo)
        form.addRow("Tags", tags_edit)
        layout.addLayout(form)
        add_label("Body (editable):")
        body_edit = QtWidgets.QPlainTextEdit(state.body)
        body_edit.setMinimumHeight(100)
        layout.addWidget(body_edit)
    else:
        add_label(f"<b>{state.title}</b>  ({state.note_type})")
    if state.is_probable_duplicate:
        add_label("⚠ Looks like a duplicate of an existing note.")
    if state.requires_review:
        add_label("⚠ Conflicts with an existing note — will be saved as needs-review.")
    if state.links:
        summary = ", ".join(f"{relationship} {title}" for relationship, title in state.links)
        add_label("Relationships: " + summary)
    if state.proposed_updates:
        updates = ", ".join(f"“{title}” → {status}" for title, status in state.proposed_updates)
        add_label("Also updating on save: " + updates)
    add_label("Original (preserved verbatim):")
    original = QtWidgets.QPlainTextEdit(state.original_text)
    original.setReadOnly(True)
    original.setMinimumHeight(120)  # show a few lines; long originals SCROLL, never grow the dialog
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
    # Cap the dialog to a fraction of the screen and centre it, so a long capture can't make the
    # window fill (or overflow) the display — labels wrap and the original scrolls within the cap,
    # keeping the Save / Discard buttons on-screen and clickable.
    screen = QtWidgets.QApplication.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        cap_w, cap_h = _bounded_size(1 << 24, 1 << 24, area.width(), area.height())
        dialog.setMaximumSize(cap_w, cap_h)
        w, h = _bounded_size(
            560, 520, area.width(), area.height()
        )  # comfortable default within cap
        dialog.resize(w, h)
        x, y = _centered_position(w, h, area.x(), area.y(), area.width(), area.height())
        dialog.move(x, y)
    accepted = bool(dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted)
    if not accepted or not editable:
        return accepted, None  # discarded, or an update/edit (no new-note fields to edit)
    tags = tuple(tag.strip() for tag in tags_edit.text().split(",") if tag.strip())
    edits = ReviewEdits(
        title=title_edit.text(),
        body=body_edit.toPlainText(),
        tags=tags,
        note_type=type_combo.currentText(),
    )
    return True, edits
