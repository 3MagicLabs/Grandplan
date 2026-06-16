"""Tests for the OllamaOrganizer adapter (parsing/validation/fallback; client injected)."""

from __future__ import annotations

import pytest

from grandplan.adapters.ollama_organizer import OllamaOrganizer, build_prompt, parse_proposed
from grandplan.core.models import NoteType, Original, Source


def _original(text: str = "Plan the launch\ndetails follow") -> Original:
    return Original.capture(text, Source(app="x"), "2026-06-15T00:00:00Z")


def test_build_prompt_includes_text_and_json_instruction() -> None:
    prompt = build_prompt("hello world")
    assert "hello world" in prompt
    assert "JSON" in prompt
    assert "title" in prompt


def test_parse_valid_json_maps_fields_and_keeps_body_verbatim() -> None:
    original = _original()
    note = parse_proposed(
        '{"title": "Launch plan", "type": "project", "tags": ["launch", "q3"]}', original
    )
    assert note.title == "Launch plan"
    assert note.type is NoteType.PROJECT
    assert note.tags == ("launch", "q3")
    assert note.body == original.text.strip()  # model never rewrites the original
    assert note.original_id == original.id


def test_parse_unknown_type_defaults_to_idea() -> None:
    assert parse_proposed('{"title": "x", "type": "bogus"}', _original()).type is NoteType.IDEA


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="."):
        parse_proposed("not json at all", _original())


def test_organizer_uses_llm_response_when_valid() -> None:
    def chat(model: str, prompt: str) -> str:
        return '{"title": "From LLM", "type": "task", "tags": ["a"]}'

    note = OllamaOrganizer(chat=chat).organize(_original())
    assert note.title == "From LLM"
    assert note.type is NoteType.TASK


def test_organizer_falls_back_on_client_failure() -> None:
    def boom(model: str, prompt: str) -> str:
        raise RuntimeError("no ollama running")

    note = OllamaOrganizer(chat=boom).organize(_original("Buy milk and eggs"))
    assert note.title == "Buy milk and eggs"  # HeuristicOrganizer fallback


def test_organizer_falls_back_on_connection_error() -> None:
    # Regression: Ollama installed but no server running raises ConnectionError (not in the
    # old catch list) — the pipeline must still degrade to the baseline, never crash.
    def refused(model: str, prompt: str) -> str:
        raise ConnectionError("connection refused: localhost:11434")

    note = OllamaOrganizer(chat=refused).organize(_original("Buy milk and eggs"))
    assert note.title == "Buy milk and eggs"  # HeuristicOrganizer fallback
