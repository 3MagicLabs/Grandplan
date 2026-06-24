"""Tests for the shared lenient JSON parser used by every local-LLM adapter (`adapters._ollama`).

The headline regression: under load a long capture fills Ollama's context window, so the
grammar-constrained (`format="json"`) reply is TRUNCATED mid-object and a bare `json.loads` fails
with `Expecting ',' delimiter` at the end of the string. `loads_lenient` must recover a usable
object from such a reply instead of discarding the whole organize/reconcile/placement.
"""

from __future__ import annotations

import json

import pytest

from grandplan.adapters._ollama import loads_lenient


def test_parses_plain_object() -> None:
    assert loads_lenient('{"title": "x", "type": "task"}') == {"title": "x", "type": "task"}


def test_parses_array() -> None:
    assert loads_lenient('["a", "b"]') == ["a", "b"]


def test_tolerates_surrounding_prose() -> None:
    # raw_decode ignores anything after the first complete value (some models add a trailing note).
    assert loads_lenient('Here is the note: {"title": "x"} hope that helps') == {"title": "x"}


def test_tolerates_code_fences() -> None:
    fenced = '```json\n{"title": "x", "tags": ["a"]}\n```'
    assert loads_lenient(fenced) == {"title": "x", "tags": ["a"]}


def test_recovers_truncated_body_string() -> None:
    # THE bug: the model was cut off mid-`body` when it hit the context window. We must still get a
    # usable note — title/type/tags intact and the body present (even if itself truncated).
    truncated = '{"title": "Launch plan", "type": "project", "tags": ["a", "b"], "body": "Summary line then a lot of detail that got cut o'
    out = loads_lenient(truncated)
    assert out["title"] == "Launch plan"
    assert out["type"] == "project"
    assert out["tags"] == ["a", "b"]
    assert out["body"].startswith("Summary line")


def test_recovers_truncated_array() -> None:
    assert loads_lenient('{"tags": ["a", "b') == {"tags": ["a", "b"]}


def test_recovers_truncated_after_comma() -> None:
    # Cut right after a complete member + comma: drop the dangling separator and close.
    assert loads_lenient('{"title": "x", "type": "task",') == {"title": "x", "type": "task"}


def test_recovers_dangling_key_without_value() -> None:
    # Cut after a key (and its colon) but before any value: drop the incomplete trailing member.
    assert loads_lenient('{"title": "x", "bod') == {"title": "x"}
    assert loads_lenient('{"title": "x", "body":') == {"title": "x"}


def test_recovers_real_world_1071_char_truncation() -> None:
    # Reproduce the reported failure: a ~1KB object truncated inside the body (char ~1071).
    body = "step one and then " * 60  # long body, definitely past col 1000
    full = json.dumps({"title": "T", "type": "task", "tags": ["x"], "body": body})
    truncated = full[:1071]
    with pytest.raises(json.JSONDecodeError):
        json.loads(truncated)  # the status quo: a hard failure → silent fallback
    out = loads_lenient(truncated)  # the fix: recover a usable note
    assert out["title"] == "T"
    assert out["type"] == "task"
    assert out["body"].startswith("step one")


def test_non_json_raises_value_error() -> None:
    with pytest.raises(ValueError):
        loads_lenient("not json at all")


def test_empty_raises_value_error() -> None:
    with pytest.raises(ValueError):
        loads_lenient("   ")


def test_valid_nested_object_unchanged() -> None:
    payload = {"a": {"b": [1, 2, {"c": "d"}]}, "e": "f"}
    assert loads_lenient(json.dumps(payload)) == payload
