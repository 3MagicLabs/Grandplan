"""Tests for the HTTP intake handler — auth, validation, playbook resolution, enqueue (pure logic)."""

from __future__ import annotations

import pytest

from grandplan.adapters.http_intake import (
    MAX_BODY_BYTES,
    bearer_token,
    check_auth,
    handle_intake,
    parse_payload,
    precheck_request,
)
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


def test_bearer_token_extracts_and_rejects() -> None:
    assert bearer_token("Bearer abc123") == "abc123"
    assert bearer_token("Basic abc123") is None
    assert bearer_token("") is None


def test_check_auth_open_when_no_token_configured() -> None:
    assert check_auth("", None) is True
    assert check_auth("", "anything") is True


def test_check_auth_constant_time_match() -> None:
    assert check_auth("secret", "secret") is True
    assert check_auth("secret", "wrong") is False
    assert check_auth("secret", None) is False


def test_precheck_allows_clean_request() -> None:
    assert precheck_request("/directive", 100, "", "") is None
    assert precheck_request("/directive/", 100, "Bearer s", "s") is None


def test_precheck_rejects_wrong_path() -> None:
    result = precheck_request("/nope", 10, "", "")
    assert result is not None and result.status == 404


def test_precheck_caps_body_before_read() -> None:
    result = precheck_request("/directive", MAX_BODY_BYTES + 1, "", "")
    assert result is not None and result.status == 413


def test_precheck_rejects_negative_length() -> None:
    result = precheck_request("/directive", -1, "", "")
    assert result is not None and result.status == 400


def test_precheck_rejects_bad_token_before_read() -> None:
    result = precheck_request("/directive", 10, "Bearer wrong", "secret")
    assert result is not None and result.status == 401
    missing = precheck_request("/directive", 10, "", "secret")
    assert missing is not None and missing.status == 401
