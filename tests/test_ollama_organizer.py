"""Tests for the OllamaOrganizer adapter (parsing/validation/fallback; client injected)."""

from __future__ import annotations

import json

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


def test_refusal_output_is_rejected_then_falls_back_to_heuristic() -> None:
    refusal = json.dumps({"title": "I cannot assist with that request"})
    with pytest.raises(ValueError, match="refusal"):
        parse_proposed(refusal, _original())

    note = OllamaOrganizer(chat=lambda m, p: refusal).organize(_original())  # retries → heuristic
    assert "cannot assist" not in note.title.lower()  # the refusal never became the note


def test_parse_maps_resources_and_skips_invalid_entries() -> None:
    from grandplan.core.resources import Resource, ResourceKind

    raw = json.dumps(
        {
            "title": "x",
            "resources": [
                {"kind": "link", "ref": "https://example.com", "label": "site"},
                {"kind": "bogus", "ref": "ignored"},  # invalid kind → skipped
                {"kind": "file", "ref": ""},  # empty ref → skipped
                "not-an-object",  # malformed entry → skipped
            ],
        }
    )
    assert parse_proposed(raw, _original()).resources == (
        Resource(ResourceKind.LINK, "https://example.com", "site"),
    )


def test_resource_ref_newlines_are_stripped_to_prevent_markdown_injection() -> None:
    raw = json.dumps(
        {"title": "x", "resources": [{"kind": "link", "ref": "https://x.com\n# evil"}]}
    )
    (resource,) = parse_proposed(raw, _original()).resources
    assert "\n" not in resource.ref


def test_absent_resources_falls_back_to_heuristic_extraction() -> None:
    from grandplan.core.resources import Resource, ResourceKind

    original = _original("ship it — see https://github.com/a/b")
    note = parse_proposed('{"title": "x"}', original)  # model omitted "resources"
    assert Resource(ResourceKind.LINK, "https://github.com/a/b") in note.resources


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="."):
        parse_proposed("not json at all", _original())


def test_organizer_uses_llm_response_when_valid() -> None:
    def chat(model: str, prompt: str) -> str:
        return '{"title": "From LLM", "type": "task", "tags": ["a"]}'

    note = OllamaOrganizer(chat=chat).organize(_original())
    assert note.title == "From LLM"
    assert note.type is NoteType.TASK


def test_organizer_uses_enhanced_body_from_llm() -> None:
    enhanced = "**Summary:** ship it.\n\n- step one\n- step two"

    def chat(model: str, prompt: str) -> str:
        return json.dumps({"title": "Launch", "type": "project", "tags": ["x"], "body": enhanced})

    note = OllamaOrganizer(chat=chat).organize(_original("raw messy capture text"))
    assert note.body == enhanced  # the model's organized body, not the verbatim original
    assert note.title == "Launch"


def test_organizer_keeps_verbatim_body_when_model_omits_it() -> None:
    def chat(model: str, prompt: str) -> str:
        return '{"title": "T", "type": "idea", "tags": []}'  # no body key

    original = _original("keep me exactly")
    note = OllamaOrganizer(chat=chat).organize(original)
    assert note.body == original.text.strip()  # never invalid — falls back to verbatim body


def test_organizer_retries_once_on_malformed_then_succeeds() -> None:
    calls: list[str] = []

    def flaky(model: str, prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return "not json at all"  # first attempt malformed
        return json.dumps({"title": "Recovered", "type": "task", "tags": [], "body": "ok"})

    note = OllamaOrganizer(chat=flaky).organize(_original())
    assert note.title == "Recovered"  # repaired on the second attempt, not the heuristic fallback
    assert len(calls) == 2


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
