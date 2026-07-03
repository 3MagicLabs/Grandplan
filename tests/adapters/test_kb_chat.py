"""KB agent chat (SPEC-AGENT-KB P1.5): a multi-turn conversation over the vault, read-only.

Extends Ask with conversation memory: each turn retrieves fresh grounding for the new question and
carries the recent dialogue so follow-ups ("what about the second one?") resolve. Same injected
transport, same degradation chain, same containment rule for citations as `kb_ask`.
"""

from __future__ import annotations

from grandplan.adapters.kb_chat import ChatSession, build_chat_prompt
from grandplan.core.models import Note, NoteType
from grandplan.core.repository import InMemoryNoteRepository


class _Embedder:
    def embed(self, text: str) -> tuple[float, ...]:
        return (1.0, 0.0)


def _repo() -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    repo.add_note(
        Note(
            id="a",
            original_id="oa",
            title="Use Postgres",
            body="we decided to use postgres for the backend",
            type=NoteType.DECISION,
        ),
        (1.0, 0.0),
    )
    return repo


def test_build_chat_prompt_includes_history_notes_and_question() -> None:
    prompt = build_chat_prompt(
        "why did we pick it?",
        history=(("user", "which db did we pick?"), ("assistant", "Postgres.")),
        notes=[("a", "Use Postgres", "we decided to use postgres")],
    )
    assert "which db did we pick?" in prompt and "Postgres." in prompt  # dialogue carried
    assert "id=a" in prompt and "we decided to use postgres" in prompt  # fresh grounding
    assert "why did we pick it?" in prompt
    assert "ONLY" in prompt  # grounding contract, same as ask


def test_chat_session_answers_and_remembers_turns() -> None:
    def chat(model: str, prompt: str) -> str:
        return '{"answer": "Postgres.", "sources": ["a"]}'

    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=chat)
    first = session.respond("which db?")
    assert first.text == "Postgres."
    assert first.sources == (("a", "Use Postgres"),)
    assert session.history == (("user", "which db?"), ("assistant", "Postgres."))


def test_chat_session_carries_history_into_the_next_prompt() -> None:
    prompts: list[str] = []

    def chat(model: str, prompt: str) -> str:
        prompts.append(prompt)
        return '{"answer": "Because of sqlite-vec.", "sources": ["a"]}'

    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=chat)
    session.respond("which db did we pick?")
    session.respond("why?")
    assert "which db did we pick?" in prompts[1]  # the follow-up sees the earlier turn


def test_chat_session_history_is_bounded() -> None:
    # A long conversation must not grow the prompt unboundedly (num_ctx is finite).
    def chat(model: str, prompt: str) -> str:
        return '{"answer": "ok", "sources": []}'

    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=chat, max_turns=2)
    for i in range(10):
        session.respond(f"question {i}?")
    assert len(session.history) == 4  # 2 exchanges (user+assistant each), older turns dropped


def test_chat_session_failed_model_degrades_to_retrieval_only_without_recording_a_turn() -> None:
    def chat(model: str, prompt: str) -> str:
        raise RuntimeError("ollama down")

    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=chat)
    answer = session.respond("which db?")
    assert answer.model is None
    assert ("a", "Use Postgres") in answer.sources  # ranked matches still returned
    assert session.history == ()  # a failed turn must not pollute later prompts


def test_chat_session_show_returns_note_body_or_none() -> None:
    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=lambda m, p: "{}")
    note = session.show("a")
    assert note is not None and "postgres" in note.body
    assert session.show("nope") is None


# -- plan drafting (#39 stage 2) -------------------------------------------------------------------

_PLAN_RAW = (
    '{"title": "Migrate to Postgres", "summary": "Move the backend to postgres.", '
    '"steps": ["set up postgres locally", "write the migration", "cut over"], '
    '"sources": ["a", "invented"]}'
)


def test_parse_plan_validates_and_filters_citations() -> None:
    from grandplan.adapters.kb_chat import parse_plan

    draft = parse_plan(_PLAN_RAW, frozenset({"a"}))
    assert draft["title"] == "Migrate to Postgres"
    assert draft["steps"] == ("set up postgres locally", "write the migration", "cut over")
    assert draft["sources"] == ("a",)  # invented id dropped (containment)


def test_parse_plan_rejects_missing_title_or_steps() -> None:
    import pytest

    from grandplan.adapters.kb_chat import parse_plan

    with pytest.raises(ValueError):
        parse_plan('{"steps": ["x"]}', frozenset())
    with pytest.raises(ValueError):
        parse_plan('{"title": "t", "steps": []}', frozenset())


def test_draft_plan_returns_grounded_draft() -> None:
    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=lambda m, p: _PLAN_RAW)
    draft = session.draft_plan("postgres migration")
    assert draft is not None
    assert draft.title == "Migrate to Postgres"
    assert draft.steps[0] == "set up postgres locally"
    assert draft.sources == (("a", "Use Postgres"),)  # (id, title), invented id filtered


def test_draft_plan_returns_none_when_no_model_or_no_notes() -> None:
    def down(model: str, prompt: str) -> str:
        raise RuntimeError("ollama down")

    assert ChatSession(repo=_repo(), embedder=_Embedder(), chat=down).draft_plan("x") is None
    empty = InMemoryNoteRepository()
    session = ChatSession(repo=empty, embedder=_Embedder(), chat=lambda m, p: _PLAN_RAW)
    assert session.draft_plan("postgres") is None  # nothing to ground a plan in


def test_render_plan_markdown_is_a_checklist() -> None:
    from grandplan.adapters.kb_chat import PlanDraft, render_plan_markdown

    draft = PlanDraft(
        title="T", summary="S.", steps=("one", "two"), sources=(("a", "Use Postgres"),), model="m"
    )
    body = render_plan_markdown(draft)
    assert body.startswith("S.")
    assert "## Next steps" in body
    assert "- [ ] one" in body and "- [ ] two" in body
