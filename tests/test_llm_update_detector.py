"""Tests for LlmUpdateDetector (prompt/parse/validate/fallback; chat client injected).

Mirrors test_llm_reconciler: the HTTP call is injected, so prompt-building, parsing, validation and
the deterministic fallback are all unit-tested with no Ollama and no [llm] extra.
"""

from __future__ import annotations

import json

import pytest

from grandplan.adapters.llm_update_detector import (
    LlmUpdateDetector,
    build_update_prompt,
    parse_update,
)
from grandplan.core.models import NoteStatus


def test_prompt_includes_text_vocabulary_and_json() -> None:
    prompt = build_update_prompt("done: built the resume")
    assert "done: built the resume" in prompt
    assert "JSON" in prompt
    for word in ("done", "active", "next", "reopen", "none"):
        assert word in prompt


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("done", NoteStatus.DONE),
        ("active", NoteStatus.ACTIVE),
        ("next", NoteStatus.NEXT),
        ("reopen", NoteStatus.ACTIVE),
    ],
)
def test_parse_maps_known_intents(key: str, expected: NoteStatus) -> None:
    assert parse_update(json.dumps({"update": key})) is expected


def test_parse_none_means_no_update() -> None:
    assert parse_update('{"update": "none"}') is None


def test_parse_unknown_intent_raises() -> None:
    with pytest.raises(ValueError, match="unknown update"):
        parse_update('{"update": "frobnicate"}')


@pytest.mark.parametrize("raw", ['{"update": null}', "{}", '{"verdict": "done"}'])
def test_parse_missing_or_null_key_raises_so_it_falls_back(raw: str) -> None:
    # A null/absent "update" means the model didn't answer → raise → heuristic fallback runs
    # (NOT silently treated as the authoritative "none" verdict, which would be a false negative).
    with pytest.raises(ValueError, match="update"):
        parse_update(raw)


def test_missing_key_falls_back_to_heuristic_not_none() -> None:
    def chat(model: str, prompt: str) -> str:
        return '{"verdict": "whoops wrong key"}'

    # Heuristic catches the "done" cue even though the LLM response omitted the expected key.
    assert LlmUpdateDetector(chat=chat).detect("done: built the resume") is NoteStatus.DONE


def test_parse_non_object_raises() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        parse_update("[1, 2, 3]")


def test_uses_llm_intent_when_valid() -> None:
    def chat(model: str, prompt: str) -> str:
        return json.dumps({"update": "next"})

    # The capture has no heuristic cue, proving the LLM's verdict (not the fallback) is used.
    assert LlmUpdateDetector(chat=chat).detect("the bug bounty research") is NoteStatus.NEXT


def test_llm_none_is_authoritative_not_fallback() -> None:
    def chat(model: str, prompt: str) -> str:
        return json.dumps({"update": "none"})

    # Heuristic would say DONE, but a successful LLM "none" is a real decision, not an error.
    assert LlmUpdateDetector(chat=chat).detect("done: built the resume") is None


def test_falls_back_to_heuristic_on_client_failure() -> None:
    def boom(model: str, prompt: str) -> str:
        raise RuntimeError("no ollama running")

    detector = LlmUpdateDetector(chat=boom)
    assert detector.detect("done: built the resume") is NoteStatus.DONE
    assert detector.detect("a plain new idea") is None


def test_falls_back_on_bad_json() -> None:
    def chat(model: str, prompt: str) -> str:
        return "not json at all"

    assert LlmUpdateDetector(chat=chat).detect("started the landing page") is NoteStatus.ACTIVE
