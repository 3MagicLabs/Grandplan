"""KB agent Ask mode (SPEC-AGENT-KB P1): retrieval-grounded Q&A over the vault, read-only.

The transport is injected (like every LLM adapter), so prompt assembly, citation validation, the
KB-model → capture-model fallback chain, and the retrieval-only degradation are all unit-tested
here; a real Ollama + pulled KB model integration-tests it on the user's machine.
"""

from __future__ import annotations

import pytest

from grandplan.adapters.kb_ask import (
    KB_DEFAULT_MODEL,
    AskAnswer,
    KbAsk,
    build_ask_prompt,
    parse_answer,
)
from grandplan.core.models import Note, NoteType
from grandplan.core.repository import InMemoryNoteRepository


class _Embedder:
    """Deterministic query embedding pointing straight at note `a`."""

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
    repo.add_note(
        Note(
            id="b",
            original_id="ob",
            title="Database options",
            body="comparing dbs: postgres vs mysql",
            type=NoteType.IDEA,
        ),
        (0.8, 0.6),
    )
    return repo


def test_build_ask_prompt_includes_question_and_each_retrieved_note() -> None:
    prompt = build_ask_prompt(
        "which database did I pick?",
        [("a", "Use Postgres", "we decided to use postgres")],
    )
    assert "which database did I pick?" in prompt
    assert "id=a" in prompt and "Use Postgres" in prompt
    assert "we decided to use postgres" in prompt
    # Grounding contract: answer ONLY from the notes, cite by id.
    assert "ONLY" in prompt


def test_parse_answer_filters_citations_to_retrieved_ids() -> None:
    raw = '{"answer": "You picked Postgres.", "sources": ["a", "hallucinated"]}'
    text, cited = parse_answer(raw, frozenset({"a", "b"}))
    assert text == "You picked Postgres."
    assert cited == ("a",)  # an id the model invented is dropped, like resource containment


def test_parse_answer_rejects_missing_answer() -> None:
    with pytest.raises(ValueError):
        parse_answer('{"sources": ["a"]}', frozenset({"a"}))


def test_ask_returns_grounded_answer_with_source_titles() -> None:
    calls: list[str] = []

    def chat(model: str, prompt: str) -> str:
        calls.append(model)
        return '{"answer": "Postgres, per your decision note.", "sources": ["a"]}'

    answer = KbAsk(repo=_repo(), embedder=_Embedder(), chat=chat).ask("which db?")
    assert answer == AskAnswer(
        text="Postgres, per your decision note.",
        sources=(("a", "Use Postgres"),),
        model=KB_DEFAULT_MODEL,
    )
    assert calls == [KB_DEFAULT_MODEL]


def test_ask_falls_back_to_capture_model_when_kb_model_unavailable() -> None:
    # SPEC-AGENT-KB open question resolved: when the KB model isn't pulled, Ask degrades to the
    # capture model rather than refusing (Garden would refuse; Ask is read-only and safe).
    calls: list[str] = []

    def chat(model: str, prompt: str) -> str:
        calls.append(model)
        if model == KB_DEFAULT_MODEL:
            raise RuntimeError("model not pulled")
        return '{"answer": "Postgres.", "sources": ["a"]}'

    answer = KbAsk(repo=_repo(), embedder=_Embedder(), chat=chat, fallback_model="cap").ask("db?")
    assert answer.model == "cap"
    assert answer.text == "Postgres."
    assert calls == [KB_DEFAULT_MODEL, "cap"]


def test_ask_degrades_to_retrieval_only_when_all_models_fail() -> None:
    # No local model at all must still be useful: return the top matching notes, no synthesis.
    def chat(model: str, prompt: str) -> str:
        raise RuntimeError("ollama down")

    answer = KbAsk(repo=_repo(), embedder=_Embedder(), chat=chat).ask("db?")
    assert answer.model is None
    assert answer.text == ""
    assert ("a", "Use Postgres") in answer.sources  # retrieval still ranked and returned


def test_ask_with_empty_vault_never_calls_the_model() -> None:
    calls: list[str] = []

    def chat(model: str, prompt: str) -> str:
        calls.append(model)
        return "{}"

    answer = KbAsk(repo=InMemoryNoteRepository(), embedder=_Embedder(), chat=chat).ask("anything?")
    assert calls == []
    assert answer.model is None and answer.sources == ()


def test_ask_skips_duplicate_fallback_when_models_are_the_same() -> None:
    # --kb-model gemma4:e4b (same as capture): one failure must not retry the identical model.
    calls: list[str] = []

    def chat(model: str, prompt: str) -> str:
        calls.append(model)
        raise RuntimeError("down")

    KbAsk(repo=_repo(), embedder=_Embedder(), chat=chat, model="m", fallback_model="m").ask("q?")
    assert calls == ["m"]
