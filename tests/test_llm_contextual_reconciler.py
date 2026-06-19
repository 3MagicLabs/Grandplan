"""Tests for the LlmContextualReconciler (neighborhood-aware; chat client injected)."""

from __future__ import annotations

from grandplan.adapters.llm_contextual_reconciler import (
    LlmContextualReconciler,
    build_reconcile_prompt,
    parse_relationships,
)
from grandplan.core.models import Note, NoteType, ProposedNote
from grandplan.core.reconcile import Relationship
from grandplan.core.repository import InMemoryNoteRepository


def _repo() -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    repo.add_note(
        Note(
            id="a",
            original_id="oa",
            title="Use Postgres",
            body="we will use postgres",
            type=NoteType.DECISION,
        ),
        (1.0, 0.0),
    )
    repo.add_note(
        Note(
            id="b",
            original_id="ob",
            title="Database options",
            body="comparing dbs",
            type=NoteType.IDEA,
        ),
        (0.8, 0.6),
    )
    return repo


def _proposed() -> ProposedNote:
    return ProposedNote(
        original_id="o",
        title="Switch to MySQL",
        body="we will use mysql instead",
        type=NoteType.DECISION,
    )


def test_prompt_includes_new_note_and_each_candidate_with_status() -> None:
    prompt = build_reconcile_prompt(
        _proposed(), [("a", "Use Postgres", "decision", "active", "we will use postgres")]
    )
    assert "Switch to MySQL" in prompt
    assert "id=a" in prompt and "Use Postgres" in prompt and "status=active" in prompt


def test_parse_relationships_keeps_valid_drops_unknown() -> None:
    rels = parse_relationships(
        '{"relationships": ['
        '{"id": "a", "relationship": "supersedes"},'
        '{"id": "x", "relationship": "related"},'  # unknown id → dropped
        '{"id": "b", "relationship": "bogus"}]}',  # unknown relationship → dropped
        {"a", "b"},
    )
    assert rels == {"a": Relationship.SUPERSEDES}


def test_reconcile_applies_per_candidate_relationships_in_one_call() -> None:
    calls = []

    def chat(model: str, prompt: str) -> str:
        calls.append(prompt)
        return '{"relationships": [{"id": "a", "relationship": "supersedes"}, {"id": "b", "relationship": "related"}]}'

    proposal = LlmContextualReconciler(chat=chat).reconcile(_proposed(), (1.0, 0.0), _repo())
    rels = {c.note.id: c.relationship for c in proposal.candidates}
    assert rels["a"] is Relationship.SUPERSEDES  # supersede drives the old note stale in the plan
    assert rels["b"] is Relationship.RELATED
    assert len(calls) == 1  # the WHOLE neighborhood classified in a single call


def test_falls_back_to_deterministic_reconciler_on_bad_json() -> None:
    proposal = LlmContextualReconciler(chat=lambda m, p: "not json").reconcile(
        _proposed(), (1.0, 0.0), _repo()
    )
    assert proposal.candidates  # the similarity fallback still produced candidates
    assert all(
        c.relationship in (Relationship.RELATED, Relationship.DUPLICATE)
        for c in proposal.candidates
    )


def test_no_similar_notes_skips_the_model() -> None:
    def must_not_call(model: str, prompt: str) -> str:
        raise AssertionError("the model must not be called when nothing is related")

    proposal = LlmContextualReconciler(chat=must_not_call).reconcile(
        _proposed(), (1.0, 0.0), InMemoryNoteRepository()
    )
    assert proposal.candidates == ()
