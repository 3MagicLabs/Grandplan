"""KB agent chat (SPEC-AGENT-KB P1.5): a multi-turn conversation over the vault, read-only.

Extends Ask with conversation memory: each turn retrieves fresh grounding for the new question and
carries the recent dialogue so follow-ups ("what about the second one?") resolve. Same injected
transport, same degradation chain, same containment rule for citations as `kb_ask`.
"""

from __future__ import annotations

from grandplan.adapters.kb_chat import ChatSession, build_chat_prompt, default_plan_context
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


# --- plan context (SPEC-ACT §A1) ----------------------------------------------------------------


def test_chat_prompt_puts_plan_context_after_the_notes() -> None:
    # The block claims the NOTES are authoritative for content — so it has to physically follow them,
    # or that sentence points at nothing.
    prompt = build_chat_prompt(
        "what should I do first?",
        history=(),
        notes=[("a", "Use Postgres", "we decided to use postgres")],
        plan="PLAN CONTEXT — critical path: Do the thing [t1]",
    )
    assert "PLAN CONTEXT" in prompt
    assert prompt.index("NOTES:") < prompt.index("PLAN CONTEXT")
    assert prompt.index("PLAN CONTEXT") < prompt.index("QUESTION:")


def test_chat_prompt_omits_the_plan_section_entirely_when_there_is_no_plan() -> None:
    prompt = build_chat_prompt("hi", history=(), notes=[("a", "T", "b")], plan="")
    assert "PLAN CONTEXT" not in prompt


def test_chat_session_injects_plan_context_into_every_turn() -> None:
    # A priority question ("what's the hardest thing?") retrieves by similarity and would otherwise
    # be answered from whatever six notes matched the wording. The plan block is what makes it real.
    prompts: list[str] = []

    def chat(model: str, prompt: str) -> str:
        prompts.append(prompt)
        return '{"answer": "ok", "sources": []}'

    session = ChatSession(
        repo=_repo(),
        embedder=_Embedder(),
        chat=chat,
        plan_context=lambda repo: "PLAN CONTEXT — critical path: Ship it [t9]",
    )
    session.respond("what's the hardest thing?")
    assert "Ship it [t9]" in prompts[0]


def test_chat_session_plan_context_can_be_disabled() -> None:
    prompts: list[str] = []

    def chat(model: str, prompt: str) -> str:
        prompts.append(prompt)
        return '{"answer": "ok", "sources": []}'

    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=chat, plan_context=None)
    session.respond("which db?")
    assert "PLAN CONTEXT" not in prompts[0]


def test_chat_session_survives_a_broken_plan_context() -> None:
    # The plan block is an enhancement, not a dependency: if projecting the plan raises, the turn
    # must still answer from retrieval rather than taking the whole conversation down.
    def chat(model: str, prompt: str) -> str:
        return '{"answer": "Postgres.", "sources": ["a"]}'

    def boom(repo: object) -> str:
        raise RuntimeError("planner exploded")

    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=chat, plan_context=boom)
    assert session.respond("which db?").text == "Postgres."


def test_chat_session_neighborhood_renders_or_none_for_unknown() -> None:
    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=lambda m, p: "{}")
    text = session.neighborhood("a")
    assert text is not None and "Use Postgres" in text
    assert session.neighborhood("nope") is None


def test_chat_session_focus_works_with_no_model_at_all() -> None:
    # /focus is pure projection. It must answer "what do I do next" when Ollama is down or the KB
    # model was never pulled — that is the whole reason it is a command and not a question.
    def dead(model: str, prompt: str) -> str:
        raise RuntimeError("ollama down")

    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=dead)
    assert "FOCUS" in session.focus()


def test_chat_session_defaults_to_a_live_plan_context() -> None:
    # Default ON: wiring the block at each call site would mean the GUI or the CLI could silently
    # ship without it, and priority questions would quietly go back to guessing.
    assert ChatSession(repo=_repo(), embedder=_Embedder()).plan_context is default_plan_context


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


# -- user-directed note improvement (#36: NEVER autonomous — only the note the user names) --------

_IMPROVE_RAW = (
    '{"title": "Use Postgres for the backend", '
    '"body": "We chose postgres.\\n\\n- driver support\\n- sqlite-vec option", '
    '"tags": ["database", "decision"], "rationale": "structured the raw sentence"}'
)


def test_draft_improvement_returns_only_changed_fields() -> None:
    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=lambda m, p: _IMPROVE_RAW)
    draft = session.draft_improvement("a")
    assert draft is not None
    assert draft.note_id == "a"
    assert draft.new_title == "Use Postgres for the backend"  # differs from "Use Postgres"
    assert draft.new_body is not None and "driver support" in draft.new_body
    assert draft.new_tags == ("database", "decision")
    assert draft.rationale == "structured the raw sentence"


def test_draft_improvement_with_no_changes_returns_none() -> None:
    def echo(model: str, prompt: str) -> str:
        # Model returns the note exactly as it is → nothing to improve, no draft to review.
        return (
            '{"title": "Use Postgres", "body": "we decided to use postgres for the backend", '
            '"tags": [], "rationale": "already clean"}'
        )

    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=echo)
    assert session.draft_improvement("a") is None


def test_draft_improvement_unknown_note_or_no_model_returns_none() -> None:
    session = ChatSession(repo=_repo(), embedder=_Embedder(), chat=lambda m, p: _IMPROVE_RAW)
    assert session.draft_improvement("nope") is None

    def down(model: str, prompt: str) -> str:
        raise RuntimeError("ollama down")

    assert ChatSession(repo=_repo(), embedder=_Embedder(), chat=down).draft_improvement("a") is None


def test_apply_improvement_is_an_append_only_edit_history_preserved(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from grandplan.adapters.kb_chat import apply_improvement_draft

    repo = _repo()
    session = ChatSession(repo=repo, embedder=_Embedder(), chat=lambda m, p: _IMPROVE_RAW)
    draft = session.draft_improvement("a")
    assert draft is not None
    apply_improvement_draft(draft, repo=repo, vault_dir=tmp_path / "vault", originals=None)
    current = repo.current_note("a")
    assert current is not None and current.title == "Use Postgres for the backend"
    assert "driver support" in current.body
    # Lossless/append-only: the STORED note is untouched; the change is a replayable edit event.
    stored = repo.get_note("a")
    assert stored is not None and stored.title == "Use Postgres"  # original creation state intact
    assert any(e.kind == "edit" for e in repo.history_of("a"))


def test_render_plan_markdown_is_a_checklist() -> None:
    from grandplan.adapters.kb_chat import PlanDraft, render_plan_markdown

    draft = PlanDraft(
        title="T", summary="S.", steps=("one", "two"), sources=(("a", "Use Postgres"),), model="m"
    )
    body = render_plan_markdown(draft)
    assert body.startswith("S.")
    assert "## Next steps" in body
    assert "- [ ] one" in body and "- [ ] two" in body


# --- scoped retrieval (SPEC-SCOPE) ---------------------------------------------------------------


class _FixedEmbedder:
    """Embeds every question to the same vector — the note embeddings do the discriminating."""

    def __init__(self, vector: tuple[float, ...]) -> None:
        self._vector = vector

    def embed(self, text: str) -> tuple[float, ...]:
        return self._vector


def _scope_repo() -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    for note_id, vector in (("n1", (1.0, 0.0)), ("n2", (0.0, 1.0)), ("n3", (0.5, 0.5))):
        note = Note(
            id=note_id,
            original_id=f"o-{note_id}",
            title=note_id,
            body=f"body {note_id}",
            type=NoteType.IDEA,
        )
        repo.add_note(note, vector)
    return repo


def test_scope_restricts_retrieval_to_the_chosen_notes() -> None:
    prompts: list[str] = []

    def chat(model: str, prompt: str) -> str:
        prompts.append(prompt)
        return '{"answer": "ok", "sources": []}'

    session = ChatSession(
        repo=_scope_repo(),
        embedder=_FixedEmbedder((1.0, 0.0)),
        chat=chat,
        plan_context=None,  # isolate retrieval — no plan block adding other ids
        scope_ids=frozenset({"n1"}),
    )
    session.respond("anything")
    assert "id=n1" in prompts[0]  # the scoped note grounds the turn
    assert (
        "id=n2" not in prompts[0] and "id=n3" not in prompts[0]
    )  # out-of-scope notes cannot enter


def test_empty_scope_uses_the_whole_vault() -> None:
    prompts: list[str] = []

    def chat(model: str, prompt: str) -> str:
        prompts.append(prompt)
        return '{"answer": "ok", "sources": []}'

    # No scope set (the default): a note the graph filter would have hidden is still reachable.
    session = ChatSession(
        repo=_scope_repo(), embedder=_FixedEmbedder((0.0, 1.0)), chat=chat, plan_context=None
    )
    session.respond("anything")
    assert "id=n2" in prompts[0]  # ranked best by similarity, whole-vault path


def test_scoped_mode_drops_the_similarity_floor() -> None:
    # A scoped note only weakly related to the question (score below _MIN_SCORE) still grounds the
    # turn: the human filter is the relevance gate now (SPEC-SCOPE §3), not the embedding floor.
    repo = InMemoryNoteRepository()
    note = Note(id="weak", original_id="o", title="Weak", body="b", type=NoteType.IDEA)
    repo.add_note(note, (0.1, 0.0))  # dot with (0.3,0) query = 0.03 < _MIN_SCORE (0.05)
    prompts: list[str] = []

    def chat(model: str, prompt: str) -> str:
        prompts.append(prompt)
        return '{"answer": "ok", "sources": []}'

    scoped = ChatSession(
        repo=repo,
        embedder=_FixedEmbedder((0.3, 0.0)),
        chat=chat,
        plan_context=None,
        scope_ids=frozenset({"weak"}),
    )
    scoped.respond("q")
    assert "id=weak" in prompts[0]  # kept — scoped threshold is 0.0

    prompts.clear()
    unscoped = ChatSession(
        repo=repo, embedder=_FixedEmbedder((0.3, 0.0)), chat=chat, plan_context=None
    )
    unscoped.respond("q")
    assert "id=weak" not in prompts[0]  # dropped — whole-vault path keeps the 0.05 floor


def test_scoped_ranking_skips_a_dimension_mismatched_embedding() -> None:
    # A note stored with a different embedder (wrong dim) must be skipped, never zipped against the
    # query and compared as noise (SPEC-SCOPE §3, the _dot strict=False hazard).
    repo = InMemoryNoteRepository()
    ok = Note(id="ok", original_id="o1", title="Ok", body="b", type=NoteType.IDEA)
    mismatched = Note(id="bad", original_id="o2", title="Bad", body="b", type=NoteType.IDEA)
    repo.add_note(ok, (1.0, 0.0))
    repo.add_note(mismatched, (1.0, 0.0, 0.0, 0.0))  # 4-dim vs the 2-dim query
    prompts: list[str] = []

    def chat(model: str, prompt: str) -> str:
        prompts.append(prompt)
        return '{"answer": "ok", "sources": []}'

    session = ChatSession(
        repo=repo,
        embedder=_FixedEmbedder((1.0, 0.0)),
        chat=chat,
        plan_context=None,
        scope_ids=frozenset({"ok", "bad"}),
    )
    session.respond("q")
    assert "id=ok" in prompts[0]
    assert "id=bad" not in prompts[0]  # skipped, not silently mis-scored


def test_instruction_allows_general_knowledge_but_grounds_user_facts() -> None:
    prompt = build_chat_prompt("q", history=(), notes=[("a", "t", "b")])
    assert "general knowledge" in prompt  # loosened: the model may reason and advise
    assert "ONLY" in prompt  # but any specific fact about the user comes only from the notes
    assert "invented" in prompt  # and never present a fabricated specific as a note fact


def test_scoped_chat_suppresses_the_whole_vault_plan_block() -> None:
    # Regression (the "handbook" leak): a scoped turn injected the whole-vault PLAN CONTEXT block
    # (critical path / actionable now / progress), which names notes OUTSIDE the scope — so the model
    # answered about the global plan, not the filtered notes. Under a scope, that block must be gone.
    prompts: list[str] = []

    def chat(model: str, prompt: str) -> str:
        prompts.append(prompt)
        return '{"answer": "ok", "sources": []}'

    session = ChatSession(
        repo=_scope_repo(),
        embedder=_FixedEmbedder((1.0, 0.0)),
        chat=chat,
        plan_context=lambda repo: "PLAN CONTEXT — critical path: Ship it [t9]",
        scope_ids=frozenset({"n1"}),
    )
    session.respond("tell me about these notes")
    assert "PLAN CONTEXT" not in prompts[0]  # the whole-vault plan is out of scope by definition
    assert "id=n1" in prompts[0]  # the scoped note is what grounds the answer


def test_live_scope_provider_refreshes_scope_each_turn() -> None:
    # Live-follow: the scope is re-read from the provider before every turn, so a graph filter the
    # user changes mid-conversation re-scopes the very next question — no manual re-sync.
    prompts: list[str] = []

    def chat(model: str, prompt: str) -> str:
        prompts.append(prompt)
        return '{"answer": "ok", "sources": []}'

    filters = iter([frozenset({"n1"}), frozenset({"n2"})])
    session = ChatSession(
        repo=_scope_repo(),
        embedder=_FixedEmbedder((1.0, 0.0)),
        chat=chat,
        plan_context=None,
        scope_provider=lambda: next(filters),
    )
    session.respond("q1")
    assert "id=n1" in prompts[0] and "id=n2" not in prompts[0]
    session.respond("q2")
    assert "id=n2" in prompts[1] and "id=n1" not in prompts[1]  # followed the changed filter


def test_live_scope_provider_failure_keeps_the_current_scope() -> None:
    # A provider that faults mid-conversation (graph.json vanished, say) must not end the turn: the
    # last resolved scope holds and the answer still comes back.
    prompts: list[str] = []

    def chat(model: str, prompt: str) -> str:
        prompts.append(prompt)
        return '{"answer": "ok", "sources": []}'

    def boom() -> frozenset[str]:
        raise RuntimeError("graph.json vanished")

    session = ChatSession(
        repo=_scope_repo(),
        embedder=_FixedEmbedder((1.0, 0.0)),
        chat=chat,
        plan_context=None,
        scope_ids=frozenset({"n1"}),
        scope_provider=boom,
    )
    answer = session.respond("q")  # must not raise
    assert answer.text == "ok"
    assert "id=n1" in prompts[0]  # kept the scope resolved before the fault
