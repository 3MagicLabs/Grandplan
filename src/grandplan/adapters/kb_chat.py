"""KB agent — chat (SPEC-AGENT-KB P1.5): multi-turn, retrieval-grounded conversation, read-only.

`grandplan ask` answers one question; a conversation needs two more things and nothing else:
**memory** (recent turns carried into the prompt so "why?" resolves against the previous answer)
and **fresh grounding per turn** (each new question re-retrieves from the vault, so the dialogue
can wander across topics without stale context). Reuses `kb_ask`'s primitives — the same JSON
answer contract, citation containment, and KB-model → capture-model → retrieval-only degradation.

The session itself is strictly read-only: it can *show* a note and *draft* a plan, but never
writes. The ONE write path is `apply_plan_draft` (#39) — called by the REPL/GUI only after the
human review gate's explicit yes, and append-only end to end (lossless, ADR-0008): an agent never
mutates the vault mid-conversation without review.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import grandplan.adapters.kb_ask as kb_ask
from grandplan.adapters._ollama import loads_lenient
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

_MAX_STEPS = 12  # a plan longer than this isn't actionable; the model is asked for fewer anyway

_IMPROVE_INSTRUCTION = (
    "You improve ONE of the user's notes: clarify the wording, structure the body as clean "
    "Markdown (a one-line summary, then bullets; keep any '- [ ]' checklist items), sharpen the "
    "title, and suggest 1-5 short lowercase topical tags. DO NOT invent facts, names, numbers, "
    "links, or commitments the note does not contain — the user's verbatim original is preserved "
    "separately no matter what. "
    'Return ONLY a JSON object with keys: "title" (improved, concise), "body" (improved Markdown), '
    '"tags" (array), and "rationale" (one sentence on what you changed and why).'
)
_PLAN_INSTRUCTION = (
    "You turn the user's notes into ONE actionable plan. Use ONLY the notes below — do not invent "
    "facts, resources, or commitments they don't imply. "
    'Return ONLY a JSON object with keys: "title" (concise plan name), "summary" (one sentence), '
    '"steps" (array of 3-8 concrete, feasible actions in logical order, each small enough to act '
    'on), and "sources" (array of the ids of the notes the plan draws on).'
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


@dataclass(frozen=True)
class PlanDraft:
    """A model-drafted, NOT-yet-applied plan (#39): the human review gate decides its fate.

    `sources` are the (id, title) of the retrieved notes the model actually drew on
    (containment-checked). Applying a draft is the caller's job — drafting never writes.
    """

    title: str
    summary: str
    steps: tuple[str, ...]
    sources: tuple[tuple[str, str], ...]
    model: str


def build_plan_prompt(topic: str, notes: Sequence[tuple[str, str, str]]) -> str:
    """Assemble the plan-drafting prompt from `(id, title, body)` retrieval hits (pure)."""
    lines = [
        f"- id={note_id} title={title!r}\n  {body[:_BODY_SNIPPET]}"
        for note_id, title, body in notes
    ]
    return f"{_PLAN_INSTRUCTION}\n\nNOTES:\n" + "\n".join(lines) + f"\n\nPLAN TOPIC:\n{topic}"


def parse_plan(raw: str, allowed_ids: frozenset[str]) -> dict[str, object]:
    """Extract a validated plan from a model reply; invented source ids dropped (containment)."""
    data = loads_lenient(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("plan has no title")
    raw_steps = data.get("steps", [])
    steps = (
        tuple(str(s).strip() for s in raw_steps if str(s).strip())[:_MAX_STEPS]
        if isinstance(raw_steps, list)
        else ()
    )
    if not steps:
        raise ValueError("plan has no steps")
    raw_sources = data.get("sources", [])
    sources = (
        tuple(str(s) for s in raw_sources if str(s) in allowed_ids)
        if isinstance(raw_sources, list)
        else ()
    )
    return {
        "title": title,
        "summary": str(data.get("summary") or "").strip(),
        "steps": steps,
        "sources": sources,
    }


def render_plan_markdown(draft: PlanDraft) -> str:
    """The plan note's body: summary line + a `- [ ]` checklist (the organizer's own convention)."""
    checklist = "\n".join(f"- [ ] {step}" for step in draft.steps)
    summary = draft.summary or draft.title
    return f"{summary}\n\n## Next steps\n{checklist}"


@dataclass(frozen=True)
class ImproveDraft:
    """A model-drafted improvement to ONE user-named note (#36) — not yet applied.

    Only the CHANGED fields are set (None = keep as-is), so applying maps 1:1 onto an append-only
    `NoteEdit` event. Never produced autonomously: the user names the note (`/improve <id>`), the
    review gate decides. `current_title`/`current_body` ride along for the before/after preview.
    """

    note_id: str
    new_title: str | None
    new_body: str | None
    new_tags: tuple[str, ...] | None
    rationale: str
    model: str
    current_title: str
    current_body: str


def build_improve_prompt(title: str, body: str, tags: Sequence[str]) -> str:
    """Assemble the single-note improvement prompt (pure)."""
    tag_line = ", ".join(tags) if tags else "(none)"
    return (
        f"{_IMPROVE_INSTRUCTION}\n\nNOTE TITLE: {title}\nNOTE TAGS: {tag_line}\nNOTE BODY:\n{body}"
    )


def parse_improvement(raw: str) -> dict[str, object]:
    """Extract a validated improvement from a model reply (title/body/tags/rationale)."""
    data = loads_lenient(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    body = str(data.get("body") or "").strip()
    if not body:
        raise ValueError("improvement has no body")
    raw_tags = data.get("tags", [])
    tags = (
        tuple(str(t).strip().lower() for t in raw_tags if str(t).strip())
        if isinstance(raw_tags, list)
        else ()
    )
    return {
        "title": str(data.get("title") or "").strip(),
        "body": body,
        "tags": tags,
        "rationale": str(data.get("rationale") or "").strip(),
    }


def apply_improvement_draft(
    draft: ImproveDraft,
    *,
    repo: NoteRepository,
    vault_dir: Path,
    originals: object = None,
) -> None:
    """Apply an APPROVED improvement as ONE append-only edit event (#36).

    Lossless by construction: the stored note and its verbatim Original are never mutated — the
    change is a replayable `NoteEdit` in the event log (exactly like a manual edit), so the full
    history stays inspectable and `regenerate` semantics are unaffected. Projections re-render so
    the improved note shows in Obsidian immediately.
    """
    from grandplan.core.models import NoteEdit
    from grandplan.core.project import write_projections

    repo.record_edit(
        draft.note_id,
        NoteEdit(title=draft.new_title, body=draft.new_body, tags=draft.new_tags),
    )
    write_projections(repo, vault_dir, originals=originals, protect_ids=frozenset({draft.note_id}))  # type: ignore[arg-type]


def apply_plan_draft(
    draft: PlanDraft,
    *,
    repo: NoteRepository,
    originals: object,
    embedder: Embedder,
    vault_dir: Path,
    created: str,
) -> str:
    """Apply an APPROVED plan draft: a new project note + `builds_on` edges to its source notes.

    The ONE write path for both the chat REPL and the GUI panel — runs only after the review
    gate's explicit yes (#39). Everything goes through the same append-only path agents use
    (`VaultWrite`): the plan text is captured as a verbatim original (lossless), the note id is
    content-addressed (idempotent re-apply), source notes are never modified — they just gain
    incoming edges. Projections re-render so the plan is visible in Obsidian immediately.
    """
    from grandplan.core.models import EdgeKind, NoteType
    from grandplan.core.project import write_projections
    from grandplan.core.write import VaultWrite

    write = VaultWrite(repo=repo, originals=originals, embedder=embedder)  # type: ignore[arg-type]
    body = render_plan_markdown(draft)
    result = write.propose_note(
        text=body, title=draft.title, type=NoteType.PROJECT.value, created=created, body=body
    )
    note_id = str(result["note_id"])
    for source_id, _title in draft.sources:
        if source_id != note_id and repo.get_note(source_id) is not None:
            write.place(note_id, source_id, EdgeKind.BUILDS_ON.value)
    write_projections(repo, vault_dir, originals=originals, today=date.fromisoformat(created[:10]))  # type: ignore[arg-type]
    return note_id


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

    def respond(
        self, question: str, *, on_answer_delta: Callable[[str], None] | None = None
    ) -> AskAnswer:
        """One chat turn. With `on_answer_delta`, the answer streams as it is generated —
        the callback receives printable answer-text pieces (JSON syntax already filtered out by
        `AnswerStreamFilter`), and the returned AskAnswer is identical to the non-streaming path."""
        hits = self.repo.most_similar(
            self.embedder.embed(question), limit=self.top_k, threshold=_MIN_SCORE
        )
        titles = {note.id: note.title for note, _score in hits}
        prompt = build_chat_prompt(
            question,
            history=self.history,
            notes=[(n.id, n.title, n.body) for n, _ in hits],
        )
        for model in self._models():
            try:
                text, cited = parse_answer(
                    self._call(model, prompt, on_answer_delta), frozenset(titles)
                )
            except Exception as exc:  # noqa: BLE001 - model not pulled, Ollama down, bad JSON
                logger.warning("chat turn with %s failed; trying next fallback: %s", model, exc)
                continue
            self._remember(question, text)
            return AskAnswer(
                text=text, sources=tuple((cid, titles[cid]) for cid in cited), model=model
            )
        # Retrieval-only: surface the ranked matches; the failed turn is NOT recorded as dialogue.
        return AskAnswer(text="", sources=tuple((n.id, n.title) for n, _ in hits), model=None)

    def _call(self, model: str, prompt: str, on_answer_delta: Callable[[str], None] | None) -> str:
        """One transport call — streaming when a delta callback is given and no test transport is
        injected. Resolved through the module at call time: kb_ask._ollama_chat (and the streaming
        twin below) are the ONE transport seam tests and future config patch."""
        if self.chat is not None:
            return self.chat(model, prompt)
        if on_answer_delta is not None:
            from grandplan.adapters.answer_stream import AnswerStreamFilter

            stream_filter = AnswerStreamFilter()

            def _raw_delta(chunk: str) -> None:
                piece = stream_filter.feed(chunk)
                if piece:
                    on_answer_delta(piece)

            return kb_ask._ollama_chat_stream(model, prompt, _raw_delta)
        return kb_ask._ollama_chat(model, prompt)

    def show(self, note_id: str) -> Note | None:
        """The full note under discussion (for the caller to display); None when unknown."""
        return self.repo.get_note(note_id)

    def draft_improvement(self, note_id: str) -> ImproveDraft | None:
        """Draft (never apply) an improvement to ONE user-named note (#36 — never autonomous).

        Returns None when the note is unknown, no local model can draft, or the model suggests no
        actual change (identical title+body+tags) — there is nothing to review in any of those
        cases. Only CHANGED fields are carried, mapping 1:1 onto the append-only edit event.
        """
        note = self.repo.current_note(note_id) or self.repo.get_note(note_id)
        if note is None:
            return None
        prompt = build_improve_prompt(note.title, note.body, note.tags)
        transport = self.chat or kb_ask._ollama_chat
        for model in self._models():
            try:
                improved = parse_improvement(transport(model, prompt))
            except Exception as exc:  # noqa: BLE001 - model not pulled, Ollama down, bad JSON
                logger.warning("improve draft with %s failed; trying next fallback: %s", model, exc)
                continue
            new_title = str(improved["title"]) or note.title
            new_body = str(improved["body"])
            new_tags = improved["tags"]
            if not isinstance(new_tags, tuple):  # parse_improvement contract; survives python -O
                raise TypeError(
                    f"improve draft tags: expected tuple, got {type(new_tags).__name__}"
                )
            draft = ImproveDraft(
                note_id=note.id,
                new_title=new_title if new_title != note.title else None,
                new_body=new_body if new_body != note.body else None,
                new_tags=new_tags if new_tags and new_tags != note.tags else None,
                rationale=str(improved["rationale"]),
                model=model,
                current_title=note.title,
                current_body=note.body,
            )
            if draft.new_title is None and draft.new_body is None and draft.new_tags is None:
                return None  # the model changed nothing — no edit to review
            return draft
        return None

    def draft_plan(self, topic: str) -> PlanDraft | None:
        """Draft (never apply) an actionable plan grounded in the notes most similar to `topic`.

        Returns None when there is nothing to ground a plan in or no local model can draft one —
        the caller surfaces the degradation. Drafting is read-only; applying an approved draft is
        the caller's job (review gate, #39). Not recorded as dialogue: a command, not a turn.
        """
        hits = self.repo.most_similar(
            self.embedder.embed(topic), limit=self.top_k, threshold=_MIN_SCORE
        )
        if not hits:
            return None
        titles = {note.id: note.title for note, _score in hits}
        prompt = build_plan_prompt(topic, [(n.id, n.title, n.body) for n, _ in hits])
        transport = self.chat or kb_ask._ollama_chat
        for model in self._models():
            try:
                plan = parse_plan(transport(model, prompt), frozenset(titles))
            except Exception as exc:  # noqa: BLE001 - model not pulled, Ollama down, bad JSON
                logger.warning("plan draft with %s failed; trying next fallback: %s", model, exc)
                continue
            source_ids = plan["sources"]
            if not isinstance(source_ids, tuple):  # parse_plan contract; survives python -O
                raise TypeError(
                    f"plan draft sources: expected tuple, got {type(source_ids).__name__}"
                )
            return PlanDraft(
                title=str(plan["title"]),
                summary=str(plan["summary"]),
                steps=plan["steps"],  # type: ignore[arg-type]
                sources=tuple((sid, titles[sid]) for sid in source_ids),
                model=model,
            )
        return None

    def _remember(self, question: str, answer: str) -> None:
        self._history.append(("user", question))
        self._history.append(("assistant", answer))
        del self._history[: -2 * self.max_turns]

    def _models(self) -> tuple[str, ...]:
        if self.fallback_model == self.model:
            return (self.model,)
        return (self.model, self.fallback_model)
