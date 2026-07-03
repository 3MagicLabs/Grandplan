"""KB agent — chat (SPEC-AGENT-KB P1.5): multi-turn, retrieval-grounded conversation, read-only.

`grandplan ask` answers one question; a conversation needs two more things and nothing else:
**memory** (recent turns carried into the prompt so "why?" resolves against the previous answer)
and **fresh grounding per turn** (each new question re-retrieves from the vault, so the dialogue
can wander across topics without stale context). Reuses `kb_ask`'s primitives — the same JSON
answer contract, citation containment, and KB-model → capture-model → retrieval-only degradation.

Still strictly read-only: the session can *show* a note but never writes. Write actions from chat
(propose/edit/status through the review gate) are the next slice, on the directive spine — an agent
must never mutate the vault mid-conversation without review (lossless, ADR-0008 append-only).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

import grandplan.adapters.kb_ask as kb_ask
from grandplan.adapters.kb_ask import (
    _MIN_SCORE,
    _TOP_K,
    KB_DEFAULT_MODEL,
    AskAnswer,
    parse_answer,
)
from grandplan.adapters.ollama_organizer import DEFAULT_MODEL, ChatClient
from grandplan.core.models import Note
from grandplan.core.ports import Embedder, NoteRepository

logger = logging.getLogger(__name__)

_MAX_TURNS = 6  # exchanges kept in the prompt; num_ctx is finite and old turns fade in relevance
_BODY_SNIPPET = 700
_HISTORY_SNIPPET = 500  # a carried turn is context, not grounding — cap it harder than notes

_INSTRUCTION = (
    "You are discussing the user's personal notes with them. Use ONLY the notes below as facts — "
    "do not add outside knowledge; if the notes do not contain the answer, say so. The conversation "
    "so far is context for what the user means, not a source of facts. "
    'Return ONLY a JSON object with keys: "answer" (a direct, conversational reply in plain text) '
    'and "sources" (array of the ids of the notes you actually used).'
)


def build_chat_prompt(
    question: str,
    *,
    history: Sequence[tuple[str, str]],
    notes: Sequence[tuple[str, str, str]],
) -> str:
    """Assemble one chat turn: instruction + recent dialogue + fresh retrieval + question (pure)."""
    parts = [_INSTRUCTION]
    if history:
        turns = "\n".join(f"{role}: {text[:_HISTORY_SNIPPET]}" for role, text in history)
        parts.append(f"CONVERSATION SO FAR:\n{turns}")
    lines = [
        f"- id={note_id} title={title!r}\n  {body[:_BODY_SNIPPET]}"
        for note_id, title, body in notes
    ]
    parts.append("NOTES:\n" + "\n".join(lines))
    parts.append(f"QUESTION:\n{question}")
    return "\n\n".join(parts)


@dataclass
class ChatSession:
    """One conversation over the vault: respond → remember → repeat. Read-only.

    Mutable by design (it *is* the conversation state); everything it returns is the frozen
    `AskAnswer`. A failed turn (retrieval-only degradation) is not recorded, so a transient
    Ollama outage can't poison the prompts of later turns.
    """

    repo: NoteRepository
    embedder: Embedder
    chat: ChatClient | None = None
    model: str = KB_DEFAULT_MODEL
    fallback_model: str = DEFAULT_MODEL
    top_k: int = _TOP_K
    max_turns: int = _MAX_TURNS
    _history: list[tuple[str, str]] = field(default_factory=list)

    @property
    def history(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._history)

    def respond(self, question: str) -> AskAnswer:
        hits = self.repo.most_similar(
            self.embedder.embed(question), limit=self.top_k, threshold=_MIN_SCORE
        )
        titles = {note.id: note.title for note, _score in hits}
        prompt = build_chat_prompt(
            question,
            history=self.history,
            notes=[(n.id, n.title, n.body) for n, _ in hits],
        )
        # Resolved through the module at call time: kb_ask._ollama_chat is the ONE transport seam
        # for both ask and chat (tests and future config patch a single place).
        transport = self.chat or kb_ask._ollama_chat
        for model in self._models():
            try:
                text, cited = parse_answer(transport(model, prompt), frozenset(titles))
            except Exception as exc:  # noqa: BLE001 - model not pulled, Ollama down, bad JSON
                logger.warning("chat turn with %s failed; trying next fallback: %s", model, exc)
                continue
            self._remember(question, text)
            return AskAnswer(
                text=text, sources=tuple((cid, titles[cid]) for cid in cited), model=model
            )
        # Retrieval-only: surface the ranked matches; the failed turn is NOT recorded as dialogue.
        return AskAnswer(text="", sources=tuple((n.id, n.title) for n, _ in hits), model=None)

    def show(self, note_id: str) -> Note | None:
        """The full note under discussion (for the caller to display); None when unknown."""
        return self.repo.get_note(note_id)

    def _remember(self, question: str, answer: str) -> None:
        self._history.append(("user", question))
        self._history.append(("assistant", answer))
        del self._history[: -2 * self.max_turns]

    def _models(self) -> tuple[str, ...]:
        if self.fallback_model == self.model:
            return (self.model,)
        return (self.model, self.fallback_model)
