"""GUI chat panel (#39 stage 3): converse with the vault, see the grounding notes live.

A window opened from the tray menu: the **left** side is the conversation (same `ChatSession` the
CLI REPL drives — dialogue memory, fresh retrieval per turn, read-only); the **right** side is a
live pane showing the actual notes grounding the current answer (title, id, body snippet — the
`/show` experience, always on) and, when a plan is drafted, a pending-proposal card with
Approve / Discard buttons. Approve routes through the ONE shared write path
(`kb_chat.apply_plan_draft` — append-only, lossless, idempotent); Discard leaves zero trace.

Threading: a chat turn is a multi-second local-LLM call, so it runs on a small worker thread and
marshals the result back to the Qt main thread via a signal (the same bridge pattern as
`gui.run_app`). One turn at a time — the input disables while the model thinks.

House split (see tests/app/test_gui_wiring.py's lesson): everything the window RENDERS —
transcript HTML, grounding pane, proposal card — is a pure, hermetically tested function here
(note titles/bodies are user data and must be escaped, never interpreted as markup); only the
thin Qt shell is `pragma: no cover` (needs Windows + the [gui] extra).
"""

from __future__ import annotations

import html
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

from grandplan.adapters.kb_ask import AskAnswer
from grandplan.adapters.kb_chat import ChatSession, ImproveDraft, PlanDraft
from grandplan.core.models import Note

if TYPE_CHECKING:
    from grandplan.app.scope_sync import ScopeResult

logger = logging.getLogger(__name__)

_WHOLE_VAULT = "scope: whole vault"  # the chip's resting text — no graph filter applied

_SNIPPET = (
    400  # chars of a grounding note's body shown in the pane (full note stays one click away)
)

# Clickable sources use a PRIVATE scheme, not `obsidian://` or `file://`, so the anchor is inert to
# anything but our own handler: QTextBrowser must never resolve it as a document to load, and a note
# title (user data) can never smuggle a real navigable target into the pane. The window turns a click
# on one of these into an `open_note(id)` callback; the vault path never reaches this module.
_NOTE_SCHEME = "grandplan-note"


def note_href(note_id: str) -> str:
    """The anchor target for a clickable source (pure). `href_note_id` is its exact inverse."""
    return f"{_NOTE_SCHEME}:{quote(note_id, safe='')}"


def href_note_id(href: str) -> str:
    """The note id inside a `note_href`, or `""` for any other link (pure).

    Fails closed: a link the window didn't author yields no id, so a click on it does nothing.
    """
    prefix = f"{_NOTE_SCHEME}:"
    return unquote(href[len(prefix) :]) if href.startswith(prefix) else ""


def _source_link(note_id: str, title: str) -> str:
    """One source rendered as a clickable anchor — id and title both escaped (pure)."""
    return f'<a href="{html.escape(note_href(note_id))}">{html.escape(title)}</a>'


class TranscriptLog:
    """Display-only conversation log (pure): the window renders EVERY exchange from here.

    `ChatSession.history` is the MODEL-facing memory and deliberately forgets failed turns (so a
    transient Ollama outage can't poison later prompts) — which meant the user's message only
    appeared once the model answered, and vanished entirely on a degraded turn. Traditional-chat
    behavior needs the opposite: echo the user's message the instant it is sent and keep every
    reply (answers, degradations, failures) visible, in order.
    """

    def __init__(self) -> None:
        self._turns: list[tuple[str, str]] = []

    def user(self, text: str) -> None:
        self._turns.append(("user", text))

    def vault(self, text: str) -> None:
        self._turns.append(("vault", text))

    @property
    def turns(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._turns)


def reply_text(answer: AskAnswer) -> str:
    """What the transcript shows for one AskAnswer — degradations become visible replies (pure)."""
    if answer.model is None:
        return (
            "no local model responded — showing the top matching notes on the right. "
            "Is Ollama running? (`ollama list` should show your models; the exact failure "
            "is in the grandplan log file)"
        )
    return answer.text or "(the model returned an empty answer — sources on the right)"


def transcript_html(turns: Sequence[tuple[str, str]]) -> str:
    """The conversation as simple HTML — speakers labelled, ALL text escaped (pure)."""
    blocks: list[str] = []
    for role, text in turns:
        speaker = "you" if role == "user" else "vault"
        colour = "#5b8def" if role == "user" else "#3fa34d"
        blocks.append(f'<p><b style="color:{colour}">{speaker}&gt;</b> {html.escape(text)}</p>')
    return "\n".join(blocks)


def grounding_html(answer: AskAnswer, *, notes: Mapping[str, Note]) -> str:
    """The live grounding pane: each source note with its id and an escaped body snippet (pure).

    Degradations are explicit, mirroring the REPL: retrieval-only (model down) says so; an empty
    result says so — the pane never just goes silently blank.
    """
    if answer.model is None and not answer.sources:
        return "<p><i>no matching notes for this turn.</i></p>"
    header = ""
    if answer.model is None:
        header = (
            "<p><i>no local model available (is Ollama running? `ollama list` shows what's "
            "installed) — top matching notes instead:</i></p>"
        )
    blocks: list[str] = [header] if header else []
    for note_id, title in answer.sources:
        note = notes.get(note_id)
        snippet = html.escape(note.body[:_SNIPPET]) if note is not None else ""
        # The title is the click target: the snippet is a 400-char preview, so the way OUT of the
        # pane and into the real note (and Obsidian's local-graph pane around it) has to be one click
        # away, not a copied id retyped into another command.
        blocks.append(
            f"<p><b>{_source_link(note_id, title)}</b> <code>[{html.escape(note_id)}]</code>"
            f"<br/><small>{snippet}</small></p>"
        )
    return "\n".join(blocks)


_READ_ONLY_FOOTER = (
    "<p><i>read-only: this is a preview and cannot be saved. Restart without --read-only "
    "to keep it.</i></p>"
)


def proposal_html(draft: PlanDraft, *, read_only: bool = False) -> str:
    """The pending-proposal card: title, summary, checklist steps, grounding sources (pure)."""
    steps = "".join(f"<li>{html.escape(step)}</li>" for step in draft.steps)
    # Clickable too: deciding whether to Approve means checking what the plan was drawn FROM.
    sources = ", ".join(_source_link(note_id, title) for note_id, title in draft.sources)
    grounded = f"<p><small>grounded in: {sources}</small></p>" if sources else ""
    # The footer must match the buttons: promising "nothing is written until you approve" beside a
    # card with no Approve button describes a gate the user cannot see or reach.
    footer = (
        _READ_ONLY_FOOTER if read_only else "<p><i>nothing is written until you approve.</i></p>"
    )
    return (
        f"<p><b>PLAN: {html.escape(draft.title)}</b><br/>{html.escape(draft.summary)}</p>"
        f"<ul>{steps}</ul>{grounded}{footer}"
    )


def improvement_html(draft: ImproveDraft, *, read_only: bool = False) -> str:
    """The pending-improvement card: rationale + before/after per changed field, escaped (pure)."""
    parts = [
        f"<p><b>IMPROVE [{html.escape(draft.note_id)}]</b><br/>{html.escape(draft.rationale)}</p>"
    ]
    if draft.new_title is not None:
        parts.append(
            f"<p>title: <s>{html.escape(draft.current_title)}</s> → "
            f"<b>{html.escape(draft.new_title)}</b></p>"
        )
    if draft.new_tags is not None:
        parts.append(f"<p>tags → {html.escape(', '.join(draft.new_tags))}</p>")
    if draft.new_body is not None:
        parts.append(f"<p>new body:</p><p><small>{html.escape(draft.new_body)}</small></p>")
    parts.append(
        _READ_ONLY_FOOTER
        if read_only
        else "<p><i>applies as ONE replayable edit; your verbatim original is preserved "
        "either way.</i></p>"
    )
    return "\n".join(parts)


def open_chat_window(  # pragma: no cover - Qt shell; needs Windows + grandplan[gui]
    *,
    session: ChatSession,
    apply_plan: Callable[[PlanDraft], str],
    apply_improve: Callable[[ImproveDraft], None],
    open_note: Callable[[str], str] | None = None,
    sync_scope: Callable[[], ScopeResult] | None = None,
    read_only: bool = False,
    parent: object = None,
) -> object:
    """Build (and return) the chat window; the caller shows it and keeps a reference.

    The window drives the injected `session` (read-only) and calls `apply_plan` ONLY from the
    Approve button — the same review-gate contract as the REPL's [y/N] prompt.

    `open_note(id)` is called when a source link is clicked; it returns `""` on success or a message
    to show the user. Injected rather than imported so this module never learns the vault path, and
    so a build without it simply renders inert links instead of failing.

    `sync_scope()` reads the current Obsidian graph filter and returns a `ScopeResult` (SPEC-SCOPE);
    the window applies its ids to the session and shows the summary in the scope chip. Injected for
    the same reason — a build without it just disables the scope button.

    `read_only` hides Approve (SPEC-READONLY §4). Drafting stays on — `draft_plan`/`draft_improvement`
    only read — so you can still see what the vault *would* propose; there is simply no way to save
    it. This is ergonomics: the ports are already sealed, so Approve could not write even if shown.
    """
    from PySide6 import QtCore, QtWidgets

    class _Bridge(QtCore.QObject):
        answered = QtCore.Signal(object)  # AskAnswer
        drafted = QtCore.Signal(object)  # PlanDraft | None
        applied = QtCore.Signal(str)  # new note id
        failed = QtCore.Signal(str)

    window = QtWidgets.QDialog(parent)  # type: ignore[arg-type]
    window.setWindowTitle(
        "grandplan — chat with your vault (read-only)"
        if read_only
        else "grandplan — chat with your vault"
    )
    window.resize(980, 560)
    bridge = _Bridge(window)

    transcript = QtWidgets.QTextBrowser()
    transcript.setOpenExternalLinks(False)
    entry = QtWidgets.QLineEdit()
    entry.setPlaceholderText(
        "ask about your notes — /scope mirror the graph filter, /focus what to do next, "
        "/graph <id> a note's connections, /plan <topic> drafts a plan, /improve <id> improves a note"
    )
    send = QtWidgets.QPushButton("Send")

    grounding = QtWidgets.QTextBrowser()
    grounding.setPlaceholderText("click a note's title to open it in Obsidian")
    proposal = QtWidgets.QTextBrowser()
    for browser in (grounding, proposal):
        # setOpenLinks(False) is what makes the click OURS: left on, QTextBrowser treats the anchor
        # as a document to navigate to and blanks the pane. anchorClicked still fires either way, so
        # without this the note opens AND the pane is destroyed.
        browser.setOpenLinks(False)
        browser.setOpenExternalLinks(False)
    approve = QtWidgets.QPushButton("Approve — save to vault")
    discard = QtWidgets.QPushButton("Discard")
    for widget in (proposal, approve, discard):
        widget.setVisible(False)

    # Scope row: one click mirrors the Obsidian graph filter into chat retrieval (SPEC-SCOPE). The
    # chip states the current sandbox so the user always knows which notes chat can and cannot reach.
    scope_button = QtWidgets.QPushButton("Scope to graph filter")
    scope_button.setEnabled(sync_scope is not None)
    scope_button.setToolTip(
        "chat only about the notes your Obsidian graph filter shows — click after filtering the graph"
    )
    scope_clear = QtWidgets.QPushButton("Clear")
    scope_clear.setEnabled(False)
    scope_chip = QtWidgets.QLabel(_WHOLE_VAULT)
    scope_chip.setWordWrap(True)
    scope_row = QtWidgets.QHBoxLayout()
    scope_row.addWidget(scope_button)
    scope_row.addWidget(scope_clear)
    scope_row.addWidget(scope_chip, 1)

    left = QtWidgets.QVBoxLayout()
    left.addLayout(scope_row)
    left.addWidget(transcript, 1)
    row = QtWidgets.QHBoxLayout()
    row.addWidget(entry, 1)
    row.addWidget(send)
    left.addLayout(row)
    right = QtWidgets.QVBoxLayout()
    right.addWidget(QtWidgets.QLabel("grounding notes"))
    right.addWidget(grounding, 2)
    right.addWidget(proposal, 1)
    actions = QtWidgets.QHBoxLayout()
    actions.addWidget(approve)
    actions.addWidget(discard)
    right.addLayout(actions)
    layout = QtWidgets.QHBoxLayout(window)
    layout.addLayout(left, 3)
    layout.addLayout(right, 2)

    pending: dict[str, PlanDraft | ImproveDraft | None] = {"draft": None}
    # The DISPLAY log: the user's message appears the instant it is sent, and degraded/failed
    # turns stay visible — session.history (the model-facing memory) drops them by design.
    log = TranscriptLog()

    def _busy(on: bool) -> None:
        entry.setEnabled(not on)
        send.setEnabled(not on)
        send.setText("thinking…" if on else "Send")

    def _refresh_transcript() -> None:
        transcript.setHtml(transcript_html(log.turns))
        scrollbar = transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _show_proposal(draft: PlanDraft | ImproveDraft | None) -> None:
        pending["draft"] = draft
        for widget in (proposal, discard):
            widget.setVisible(draft is not None)
        approve.setVisible(draft is not None and not read_only)  # sealed anyway; don't offer it
        if isinstance(draft, PlanDraft):
            proposal.setHtml(proposal_html(draft, read_only=read_only))
        elif isinstance(draft, ImproveDraft):
            proposal.setHtml(improvement_html(draft, read_only=read_only))

    def _do_scope(arg: str) -> None:
        """Sync (or clear) the retrieval scope from the Obsidian graph filter (SPEC-SCOPE).

        Instant — a file read, no model — so it runs on the UI thread like /focus. The chip states
        the sandbox; the full summary (filter text, any ignored operators) goes to the transcript.
        """
        if arg in ("off", "clear", "none"):
            session.scope_ids = frozenset()
            scope_chip.setText(_WHOLE_VAULT)
            scope_clear.setEnabled(False)
            log.vault("scope cleared — chatting over the whole vault.")
            _refresh_transcript()
            return
        if sync_scope is None:
            log.vault("(scope needs a vault on disk — not available here)")
            _refresh_transcript()
            return
        try:
            result = sync_scope()
        except Exception as exc:  # noqa: BLE001 - a broken graph config must not crash the UI
            logger.exception("scope sync failed")  # traceback to the #5 file log
            log.vault(f"could not read the graph filter: {exc}")
            _refresh_transcript()
            return
        session.scope_ids = result.ids
        scope_chip.setText(f"scope: {result.count} notes" if result.ids else _WHOLE_VAULT)
        scope_clear.setEnabled(bool(result.ids))
        log.vault(result.summary())
        _refresh_transcript()

    def _submit() -> None:
        text = entry.text().strip()
        if not text:
            return
        entry.clear()
        log.user(text)  # echo immediately — the message must never sit invisible while "thinking…"
        _refresh_transcript()
        if text.startswith("/scope"):
            _do_scope(text.removeprefix("/scope").strip().lower())
            return
        if text in ("/focus", "/next") or text.startswith("/graph"):
            # Pure projections: no model, no thread, no "thinking…" — they answer instantly and stay
            # correct with Ollama down, which is precisely why they are commands and not questions.
            try:
                if text.startswith("/graph"):
                    note_id = text.removeprefix("/graph").strip()
                    log.vault(
                        (session.neighborhood(note_id) or f"no note with id {note_id!r}")
                        if note_id
                        else "usage: /graph <note-id>"
                    )
                else:
                    log.vault(session.focus())
            except Exception as exc:  # noqa: BLE001 - never crash the UI thread
                logger.exception("chat projection failed")  # traceback to the #5 file log
                log.vault(f"could not project that: {exc}")
            _refresh_transcript()
            return
        _busy(True)
        if text.startswith("/improve"):
            target = text.removeprefix("/improve").strip()

            def _improve() -> None:
                try:
                    bridge.drafted.emit(session.draft_improvement(target))
                except Exception as exc:  # noqa: BLE001 - never crash the UI thread's worker
                    logger.exception("chat improve-draft failed")  # traceback to the #5 file log
                    bridge.failed.emit(str(exc))

            threading.Thread(target=_improve, name="grandplan-chat", daemon=True).start()
            return
        if text.startswith("/plan"):
            topic = text.removeprefix("/plan").strip()

            def _draft() -> None:
                try:
                    bridge.drafted.emit(session.draft_plan(topic))
                except Exception as exc:  # noqa: BLE001 - never crash the UI thread's worker
                    logger.exception("chat plan-draft failed")  # traceback to the #5 file log
                    bridge.failed.emit(str(exc))

            threading.Thread(target=_draft, name="grandplan-chat", daemon=True).start()
            return

        def _respond() -> None:
            try:
                bridge.answered.emit(session.respond(text))
            except Exception as exc:  # noqa: BLE001
                logger.exception("chat turn failed")  # traceback to the #5 file log
                bridge.failed.emit(str(exc))

        threading.Thread(target=_respond, name="grandplan-chat", daemon=True).start()

    def _on_answered(answer: AskAnswer) -> None:
        _busy(False)
        log.vault(reply_text(answer))
        _refresh_transcript()
        shown = {
            note_id: note
            for note_id, _title in answer.sources
            if (note := session.show(note_id)) is not None
        }
        grounding.setHtml(grounding_html(answer, notes=shown))

    def _on_drafted(draft: PlanDraft | ImproveDraft | None) -> None:
        _busy(False)
        if draft is None:
            log.vault(
                "nothing to propose — no matching notes / unknown note id, no local model "
                "available, or no changes suggested."
            )
            _refresh_transcript()
            grounding.setHtml(
                "<p><i>nothing to propose — no matching notes / unknown note id, no local "
                "model available, or no changes suggested.</i></p>"
            )
            return
        log.vault("drafted — review the proposal on the right (Approve / Discard).")
        _refresh_transcript()
        _show_proposal(draft)

    def _on_approve() -> None:
        draft = pending["draft"]
        if draft is None:
            return
        _show_proposal(None)
        _busy(True)

        def _apply() -> None:
            try:
                if isinstance(draft, ImproveDraft):
                    apply_improve(draft)
                    bridge.applied.emit(draft.note_id)
                else:
                    bridge.applied.emit(apply_plan(draft))
            except Exception as exc:  # noqa: BLE001
                logger.exception("proposal apply failed")  # traceback to the #5 file log
                bridge.failed.emit(str(exc))

        threading.Thread(target=_apply, name="grandplan-chat", daemon=True).start()

    def _on_applied(note_id: str) -> None:
        _busy(False)
        log.vault(f"✓ applied to the vault [{note_id}]")
        _refresh_transcript()
        grounding.setHtml(f"<p>✓ applied to the vault <code>[{html.escape(note_id)}]</code></p>")

    def _on_failed(message: str) -> None:
        _busy(False)
        logger.warning("chat window action failed: %s", message)
        log.vault(f"action failed: {message}")  # the turn must not silently vanish
        _refresh_transcript()
        grounding.setHtml(f"<p><i>action failed: {html.escape(message)}</i></p>")

    def _on_anchor(url: object) -> None:
        note_id = href_note_id(url.toString())  # type: ignore[attr-defined]
        if not note_id or open_note is None:
            return  # a link we didn't author, or a build with no opener wired: do nothing
        try:
            problem = open_note(note_id)
        except Exception as exc:  # noqa: BLE001 - a failed open must never kill the window
            logger.exception("opening note %s in Obsidian failed", note_id)
            problem = str(exc)
        if problem:
            # Into the transcript, not a dialog: the click failed for a reason worth reading (stale
            # projections), and the conversation is where the user is already looking.
            log.vault(problem)
            _refresh_transcript()

    grounding.anchorClicked.connect(_on_anchor)
    proposal.anchorClicked.connect(_on_anchor)
    bridge.answered.connect(_on_answered)
    bridge.drafted.connect(_on_drafted)
    bridge.applied.connect(_on_applied)
    bridge.failed.connect(_on_failed)
    send.clicked.connect(_submit)
    entry.returnPressed.connect(_submit)
    approve.clicked.connect(_on_approve)
    discard.clicked.connect(lambda: _show_proposal(None))
    scope_button.clicked.connect(lambda: _do_scope(""))
    scope_clear.clicked.connect(lambda: _do_scope("off"))
    return window
