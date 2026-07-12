"""Tests for the mobile surface serializers + decision-path parser (the web app is a static shell)."""

from __future__ import annotations

import json

from grandplan.app.coordinator import ItemState, PendingReviewView, QueueItem, Stage
from grandplan.app.mobile_api import (
    MOBILE_APP_HTML,
    parse_decision_path,
    pending_to_json,
    queue_to_json,
)
from grandplan.app.review import ReviewState


def _item(**kw: object) -> QueueItem:
    base: dict[str, object] = dict(
        id="3",
        snippet="a captured thought",
        source="phone",
        state=ItemState.QUEUED,
        stage=None,
        position=2,
        detail="",
    )
    base.update(kw)
    return QueueItem(**base)  # type: ignore[arg-type]


def test_queue_item_serialises_state_and_stage() -> None:
    in_flight = _item(state=ItemState.IN_FLIGHT, stage=Stage.ANALYZING, position=0)
    rows = queue_to_json([in_flight, _item()])
    assert rows[0]["state"] == "in_flight" and rows[0]["stage"] == "analyzing"
    assert rows[1]["state"] == "queued" and rows[1]["stage"] is None  # queued → no live stage
    assert rows[1]["position"] == 2 and rows[1]["source"] == "phone"
    # Must be JSON-encodable (no enums leak through).
    json.dumps(rows)


def test_pending_view_serialises_the_review_state() -> None:
    state = ReviewState(
        original_text="call the dentist tomorrow",
        title="Call the dentist",
        note_type="task",
        tags=("health",),
        related_titles=("Dentist appointment",),
        is_probable_duplicate=False,
        links=(("relates", "Dentist appointment"),),
    )
    view = PendingReviewView(id="7", state=state, source="phone", snippet="call the dentist")
    payload = pending_to_json([view])[0]
    assert payload["id"] == "7" and payload["title"] == "Call the dentist"
    assert payload["note_type"] == "task" and payload["tags"] == ["health"]
    assert payload["original_text"] == "call the dentist tomorrow"
    assert payload["links"] == [["relates", "Dentist appointment"]]
    assert payload["is_probable_duplicate"] is False
    json.dumps(payload)  # fully JSON-encodable


def test_parse_decision_path_reads_id_and_action() -> None:
    assert parse_decision_path("/api/pending/42/approve") == ("42", True)
    assert parse_decision_path("/api/pending/42/discard") == ("42", False)
    assert parse_decision_path("/api/pending/abc-9/approve/") == (
        "abc-9",
        True,
    )  # trailing slash ok


def test_parse_decision_path_rejects_other_routes() -> None:
    assert parse_decision_path("/api/queue") is None
    assert parse_decision_path("/api/pending/42") is None  # no action
    assert parse_decision_path("/api/pending/42/delete") is None  # unknown action
    assert parse_decision_path("/other/42/approve") is None


def test_web_app_is_self_contained_and_wired_to_the_api() -> None:
    # Self-contained (offline / CSP-safe) and points at the real endpoints + token scheme.
    html = MOBILE_APP_HTML
    assert html.lstrip().startswith("<!doctype html>")
    assert "/api/queue" in html and "/api/pending" in html
    assert "Authorization" in html and "Bearer" in html and "token" in html
    assert "http://" not in html and "https://" not in html  # no external requests
