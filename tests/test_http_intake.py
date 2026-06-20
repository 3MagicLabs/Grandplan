"""Tests for the HTTP intake handler — auth, validation, playbook resolution, enqueue (pure logic)."""

from __future__ import annotations

import pytest

from grandplan.adapters.http_intake import handle_intake, parse_payload
from grandplan.core.directive import InMemoryDirectiveStore


def test_handle_intake_enqueues_with_playbook() -> None:
    store = InMemoryDirectiveStore()
    result = handle_intake(
        store,
        {"content": "profile Sarah Chen", "playbook": "profile-and-connect"},
        "2026-06-20",
    )
    assert result.status == 201
    assert result.body["playbook"] == "profile-and-connect"
    assert len(store.pending()) == 1


def test_handle_intake_accepts_ad_hoc_prompt() -> None:
    store = InMemoryDirectiveStore()
    result = handle_intake(store, {"content": "x", "prompt": "summarize it"}, "2026")
    assert result.status == 201
    assert store.pending()[0].instruction == "summarize it"


def test_handle_intake_rejects_missing_content() -> None:
    result = handle_intake(InMemoryDirectiveStore(), {"playbook": "capture-and-file"}, "2026")
    assert result.status == 400
    assert "content" in result.body["error"]


def test_handle_intake_rejects_unknown_playbook() -> None:
    result = handle_intake(InMemoryDirectiveStore(), {"content": "x", "playbook": "nope"}, "2026")
    assert result.status == 400


def test_handle_intake_requires_instruction() -> None:
    # neither playbook nor prompt → resolve_instruction raises → 400
    result = handle_intake(InMemoryDirectiveStore(), {"content": "x"}, "2026")
    assert result.status == 400


def test_handle_intake_enforces_token() -> None:
    store = InMemoryDirectiveStore()
    payload = {"content": "x", "prompt": "do it"}
    assert handle_intake(store, payload, "2026", token="secret").status == 401
    assert (
        handle_intake(store, payload, "2026", token="secret", provided_token="wrong").status == 401
    )
    ok = handle_intake(store, payload, "2026", token="secret", provided_token="secret")
    assert ok.status == 201


def test_handle_intake_is_idempotent_on_identical_content() -> None:
    store = InMemoryDirectiveStore()
    payload = {"content": "same", "prompt": "do it"}
    a = handle_intake(store, payload, "2026")
    b = handle_intake(store, payload, "2026")
    assert a.body["id"] == b.body["id"]
    assert len(store.all()) == 1


def test_parse_payload_valid() -> None:
    assert parse_payload(b'{"content": "hi"}') == {"content": "hi"}


def test_parse_payload_rejects_bad_json() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_payload(b"not json")


def test_parse_payload_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        parse_payload(b"[1, 2]")
