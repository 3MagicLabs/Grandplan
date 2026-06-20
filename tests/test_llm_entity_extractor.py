"""Tests for LlmEntityExtractor — prompt, parse/sanitize, heuristic union, and fallback."""

from __future__ import annotations

from grandplan.adapters.llm_entity_extractor import (
    LlmEntityExtractor,
    build_entity_prompt,
    parse_entities,
)
from grandplan.core.entities import EntityMention


def test_prompt_includes_text_and_instruction() -> None:
    prompt = build_entity_prompt("ping Sarah Chen")
    assert "ping Sarah Chen" in prompt
    assert "JSON" in prompt


def test_parse_entities_sanitizes_and_dedupes() -> None:
    raw = '{"entities": ["Sarah Chen", "  Sarah   Chen ", "Anthropic", 42, ""]}'
    names = [m.name for m in parse_entities(raw)]
    assert names == [
        "Sarah Chen",
        "Anthropic",
    ]  # whitespace-normalized, deduped, non-strings dropped


def test_parse_entities_drops_overlong_names() -> None:
    raw = '{"entities": ["' + "x" * 200 + '", "Bob Smith"]}'
    assert [m.name for m in parse_entities(raw)] == ["Bob Smith"]


def test_parse_entities_missing_list_returns_empty() -> None:
    assert parse_entities('{"foo": 1}') == ()


def test_parse_entities_non_object_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="JSON object"):
        parse_entities("[1, 2, 3]")


def test_extractor_unions_llm_and_heuristic() -> None:
    # the model finds "Anthropic"; the heuristic independently finds the @handle and proper noun.
    extractor = LlmEntityExtractor(chat=lambda model, prompt: '{"entities": ["Anthropic"]}')
    names = {m.name for m in extractor.extract("@maria and Sarah Chen at Anthropic")}
    assert {"Anthropic", "@maria", "Sarah Chen"} <= names


def test_extractor_falls_back_to_heuristic_on_bad_json() -> None:
    extractor = LlmEntityExtractor(chat=lambda model, prompt: "not json")
    names = {m.name for m in extractor.extract("ping Sarah Chen")}
    assert "Sarah Chen" in names  # heuristic still works


def test_extractor_falls_back_on_chat_error() -> None:
    def boom(model: str, prompt: str) -> str:
        raise RuntimeError("ollama down")

    extractor = LlmEntityExtractor(chat=boom)
    assert EntityMention("Sarah Chen") in extractor.extract("call Sarah Chen")
