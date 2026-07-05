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

from grandplan.adapters.kb_ask import AskAnswer
from grandplan.adapters.kb_chat import ChatSession, ImproveDraft, PlanDraft
from grandplan.core.models import Note

logger = logging.getLogger(__name__)

_SNIPPET = (
    400  # chars of a grounding note's body shown in the pane (full note stays one click away)
)


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
        header = "<p><i>no local model available — top matching notes instead:</i></p>"
    blocks: list[str] = [header] if header else []
    for note_id, title in answer.sources:
        note = notes.get(note_id)
        snippet = html.escape(note.body[:_SNIPPET]) if note is not None else ""
        blocks.append(
            f"<p><b>{html.escape(title)}</b> <code>[{html.escape(note_id)}]</code>"
            f"<br/><small>{snippet}</small></p>"
        )
    return "\n".join(blocks)


def proposal_html(draft: PlanDraft) -> str:
    """The pending-proposal card: title, summary, checklist steps, grounding sources (pure)."""
    steps = "".join(f"<li>{html.escape(step)}</li>" for step in draft.steps)
    sources = ", ".join(html.escape(title) for _id, title in draft.sources)
    grounded = f"<p><small>grounded in: {sources}</small></p>" if sources else ""
    return (
        f"<p><b>PLAN: {html.escape(draft.title)}</b><br/>{html.escape(draft.summary)}</p>"
        f"<ul>{steps}</ul>{grounded}"
        "<p><i>nothing is written until you approve.</i></p>"
    )


def improvement_html(draft: ImproveDraft) -> str:
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
        "<p><i>applies as ONE replayable edit; your verbatim original is preserved either way.</i></p>"
    )
    return "\n".join(parts)


def open_chat_window(  # pragma: no cover - Qt shell; needs Windows + grandplan[gui]
    *,
    session: ChatSession,
    apply_plan: Callable[[PlanDraft], str],
    apply_improve: Callable[[ImproveDraft], None],
    parent: object = None,
) -> object:
    """Build (and return) the chat window; the caller shows it and keeps a reference.

    The window drives the injected `session` (read-only) and calls `apply_plan` ONLY from the
    Approve button — the same review-gate contract as the REPL's [y/N] prompt.
    """
    from PySide6 import QtCore, QtWidgets

    class _Bridge(QtCore.QObject):
        answered = QtCore.Signal(object)  # AskAnswer
        drafted = QtCore.Signal(object)  # PlanDraft | None
        applied = QtCore.Signal(str)  # new note id
        failed = QtCore.Signal(str)

    window = QtWidgets.QDialog(parent)  # type: ignore[arg-type]
    window.setWindowTitle("grandplan — chat with your vault")
    window.resize(980, 560)
    bridge = _Bridge(window)

    transcript = QtWidgets.QTextBrowser()
    transcript.setOpenExternalLinks(False)
    entry = QtWidgets.QLineEdit()
    entry.setPlaceholderText(
        "ask about your notes — /plan <topic> drafts a plan, /improve <id> improves a note"
    )
    send = QtWidgets.QPushButton("Send")

    grounding = QtWidgets.QTextBrowser()
    grounding.setPlaceholderText("the notes grounding each answer appear here")
    proposal = QtWidgets.QTextBrowser()
    approve = QtWidgets.QPushButton("Approve — save to vault")
    discard = QtWidgets.QPushButton("Discard")
    for widget in (proposal, approve, discard):
        widget.setVisible(False)

    left = QtWidgets.QVBoxLayout()
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

    def _busy(on: bool) -> None:
        entry.setEnabled(not on)
        send.setEnabled(not on)
        send.setText("thinking…" if on else "Send")

    def _refresh_transcript() -> None:
        transcript.setHtml(transcript_html(session.history))
        scrollbar = transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _show_proposal(draft: PlanDraft | ImproveDraft | None) -> None:
        pending["draft"] = draft
        for widget in (proposal, approve, discard):
            widget.setVisible(draft is not None)
        if isinstance(draft, PlanDraft):
            proposal.setHtml(proposal_html(draft))
        elif isinstance(draft, ImproveDraft):
            proposal.setHtml(improvement_html(draft))

    def _submit() -> None:
        text = entry.text().strip()
        if not text:
            return
        entry.clear()
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
            grounding.setHtml(
                "<p><i>nothing to propose — no matching notes / unknown note id, no local "
                "model available, or no changes suggested.</i></p>"
            )
            return
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
        grounding.setHtml(f"<p>✓ applied to the vault <code>[{html.escape(note_id)}]</code></p>")

    def _on_failed(message: str) -> None:
        _busy(False)
        logger.warning("chat window action failed: %s", message)
        grounding.setHtml(f"<p><i>action failed: {html.escape(message)}</i></p>")

    bridge.answered.connect(_on_answered)
    bridge.drafted.connect(_on_drafted)
    bridge.applied.connect(_on_applied)
    bridge.failed.connect(_on_failed)
    send.clicked.connect(_submit)
    entry.returnPressed.connect(_submit)
    approve.clicked.connect(_on_approve)
    discard.clicked.connect(lambda: _show_proposal(None))
    return window
