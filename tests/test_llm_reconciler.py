"""Tests for LlmRelationshipClassifier (prompt/parse/validate/fallback; client injected)."""

from __future__ import annotations

import json

import pytest

from grandplan.adapters.llm_reconciler import (
    LlmRelationshipClassifier,
    build_classify_prompt,
    parse_relationship,
)
from grandplan.core.models import Note, NoteType, ProposedNote
from grandplan.core.reconcile import Relationship


def _new(title: str = "New idea") -> ProposedNote:
    return ProposedNote(original_id="o", title=title, body="new body", type=NoteType.IDEA)


def _candidate(title: str = "Old idea") -> Note:
    return Note(id="c1", original_id="oc", title=title, body="old body", type=NoteType.IDEA)


def test_prompt_includes_both_notes_and_json_instruction() -> None:
    prompt = build_classify_prompt(_new("AAA"), _candidate("BBB"))
    assert "AAA" in prompt and "BBB" in prompt
    assert "JSON" in prompt
    assert "supersedes" in prompt and "contradicts" in prompt


def test_parse_valid_relationship() -> None:
    assert parse_relationship('{"relationship": "supersedes"}') is Relationship.SUPERSEDES


def test_parse_unknown_relationship_raises() -> None:
    with pytest.raises(ValueError, match="unknown relationship"):
        parse_relationship('{"relationship": "frobnicate"}')


def test_parse_non_object_raises() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        parse_relationship("[1, 2, 3]")


def test_uses_llm_relationship_when_valid() -> None:
    def chat(model: str, prompt: str) -> str:
        return json.dumps({"relationship": "builds_on"})

    classifier = LlmRelationshipClassifier(chat=chat)
    assert classifier.classify(_new(), _candidate(), 0.5) is Relationship.BUILDS_ON


def test_falls_back_to_similarity_on_client_failure() -> None:
    def boom(model: str, prompt: str) -> str:
        raise RuntimeError("no ollama running")

    classifier = LlmRelationshipClassifier(chat=boom)
    # similarity fallback: a high score → duplicate, a low score → related (deterministic)
    assert classifier.classify(_new(), _candidate(), 0.99) is Relationship.DUPLICATE
    assert classifier.classify(_new(), _candidate(), 0.10) is Relationship.RELATED


def test_falls_back_on_unknown_relationship() -> None:
    def chat(model: str, prompt: str) -> str:
        return '{"relationship": "nonsense"}'

    classifier = LlmRelationshipClassifier(chat=chat)
    assert classifier.classify(_new(), _candidate(), 0.10) is Relationship.RELATED  # fallback band
