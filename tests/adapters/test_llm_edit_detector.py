"""Tests for LlmEditDetector (prompt/parse/validate/fallback; chat client injected)."""

from __future__ import annotations

import json

import pytest

from grandplan.adapters.llm_edit_detector import (
    LlmEditDetector,
    build_edit_prompt,
    parse_edit,
)
from grandplan.core.models import NoteEdit


def test_prompt_includes_text_fields_and_json() -> None:
    prompt = build_edit_prompt("launch slipped to Q3")
    assert "launch slipped to Q3" in prompt
    assert "JSON" in prompt
    for field in ("title", "body", "tags", "due"):
        assert field in prompt


def test_parse_maps_fields() -> None:
    edit = parse_edit(json.dumps({"edit": {"due": "Q3", "title": "Launch v2"}}))
    assert edit == NoteEdit(due="Q3", title="Launch v2")


def test_parse_maps_tags_to_a_tuple() -> None:
    edit = parse_edit(json.dumps({"edit": {"tags": ["launch", "q3"]}}))
    assert edit == NoteEdit(tags=("launch", "q3"))


def test_parse_null_edit_is_none() -> None:
    assert parse_edit('{"edit": null}') is None


def test_parse_empty_edit_is_none() -> None:
    # The model said "edit" but set no fields → nothing to change → no edit (not an error).
    assert parse_edit('{"edit": {}}') is None


@pytest.mark.parametrize("raw", ['{"verdict": "x"}', "[1, 2, 3]", '{"edit": 5}'])
def test_parse_invalid_shape_raises(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_edit(raw)


def test_uses_llm_edit_when_valid() -> None:
    def chat(model: str, prompt: str) -> str:
        return json.dumps({"edit": {"body": "now blocked on legal review"}})

    # No heuristic cue in the text, proving the LLM's edit (not the fallback) is used.
    assert LlmEditDetector(chat=chat).detect("an update about the launch") == NoteEdit(
        body="now blocked on legal review"
    )


def test_llm_null_is_authoritative_not_fallback() -> None:
    def chat(model: str, prompt: str) -> str:
        return json.dumps({"edit": None})

    # Heuristic would extract a due here, but a successful LLM "null" is a real "no edit" decision.
    assert LlmEditDetector(chat=chat).detect("launch slipped to Q3") is None


def test_falls_back_to_heuristic_on_client_failure() -> None:
    def boom(model: str, prompt: str) -> str:
        raise RuntimeError("no ollama running")

    detector = LlmEditDetector(chat=boom)
    assert detector.detect("rename it to CV") == NoteEdit(title="CV")
    assert detector.detect("a plain new idea") is None


def test_falls_back_on_bad_json() -> None:
    def chat(model: str, prompt: str) -> str:
        return "not json"

    assert LlmEditDetector(chat=chat).detect("launch slipped to Q3") == NoteEdit(due="Q3")
