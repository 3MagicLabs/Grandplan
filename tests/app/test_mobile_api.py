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
        proposed_updates=(("Old dentist note", "done"),),
        body="Call the dentist office to book a cleaning.",
    )
    view = PendingReviewView(id="7", state=state, source="phone", snippet="call the dentist")
    payload = pending_to_json([view])[0]
    assert payload["id"] == "7" and payload["title"] == "Call the dentist"
    assert payload["note_type"] == "task" and payload["tags"] == ["health"]
    assert payload["original_text"] == "call the dentist tomorrow"  # the verbatim capture, shown
    assert payload["links"] == [["relates", "Dentist appointment"]]  # typed relationships
    assert payload["proposed_updates"] == [["Old dentist note", "done"]]  # side-effects on save
    assert payload["is_probable_duplicate"] is False
    assert payload["body"] == state.body  # the editable body is exposed to the phone
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
    # Review parity with the desktop dialog: the card renders the verbatim original + relationships +
    # save-time side-effects, not just the title/tags.
    assert "original_text" in html and "relationships" in html and "proposed_updates" in html
    # Inline editing: the card has editable fields and Save posts them as a JSON body of edits.
    assert (
        "edit-title" in html and "edit-body" in html and "edit-tags" in html and "edit-type" in html
    )
    assert "Content-Type" in html and "application/json" in html


# -- request handlers (auth + routing; the socket shell in http_intake just calls these) ----------

from grandplan.app.mobile_api import handle_mobile_decision, handle_mobile_get  # noqa: E402

_QUEUE = lambda: [{"id": "1", "snippet": "x", "state": "queued"}]  # noqa: E731
_PENDING = lambda: [{"id": "2", "title": "y"}]  # noqa: E731


def test_get_root_serves_the_public_web_app_shell() -> None:
    # The page itself needs no token (it has no data) — it authenticates its own /api calls.
    result = handle_mobile_get(
        "/?token=whatever", None, token="secret", queue=_QUEUE, pending=_PENDING
    )
    assert result.status == 200
    assert result.content_type.startswith("text/html")
    assert result.text is not None and result.text.lstrip().startswith("<!doctype html>")


def test_get_apis_are_token_gated() -> None:
    q = handle_mobile_get("/api/queue", "secret", token="secret", queue=_QUEUE, pending=_PENDING)
    assert q.status == 200 and q.body == {"queue": _QUEUE()}
    p = handle_mobile_get("/api/pending", "secret", token="secret", queue=_QUEUE, pending=_PENDING)
    assert p.status == 200 and p.body == {"pending": _PENDING()}
    bad = handle_mobile_get("/api/queue", "wrong", token="secret", queue=_QUEUE, pending=_PENDING)
    assert bad.status == 401  # wrong token → refused
    open_ = handle_mobile_get("/api/queue", None, token="", queue=_QUEUE, pending=_PENDING)
    assert open_.status == 200  # no token configured → open (localhost default)


def test_get_unknown_route_is_404() -> None:
    assert (
        handle_mobile_get("/api/nope", None, token="", queue=_QUEUE, pending=_PENDING).status == 404
    )


def test_decision_routes_to_the_coordinator_and_is_gated() -> None:
    calls: list[tuple[str, bool, object]] = []

    def decide(pid: str, approve: bool, edits: object) -> bool:
        calls.append((pid, approve, edits))
        return True

    ok = handle_mobile_decision("/api/pending/5/approve", "s", token="s", decide=decide)
    assert ok.status == 200 and ok.body == {"resolved": True}
    assert calls == [("5", True, None)]  # plain approve (no body) → no edits
    assert handle_mobile_decision("/api/pending/5/discard", "s", token="s", decide=decide).body == {
        "resolved": True
    }
    assert calls[-1] == ("5", False, None)
    assert (
        handle_mobile_decision("/api/pending/5/approve", "no", token="s", decide=decide).status
        == 401
    )
    assert (
        handle_mobile_decision("/api/pending/5/bogus", "s", token="s", decide=decide).status == 404
    )


def test_decision_applies_edits_from_the_body() -> None:
    seen: list[object] = []

    def decide(pid: str, approve: bool, edits: object) -> bool:
        seen.append(edits)
        return True

    body = json.dumps(
        {"title": "Fixed title", "body": "new body", "tags": ["a", "b"], "note_type": "task"}
    ).encode()
    handle_mobile_decision("/api/pending/9/approve", "s", token="s", decide=decide, body=body)
    edits = seen[0]
    assert edits is not None
    assert edits.title == "Fixed title" and edits.tags == ("a", "b")  # type: ignore[attr-defined]
    assert edits.note_type == "task" and edits.body == "new body"  # type: ignore[attr-defined]
    # A discard never carries edits, even with a body.
    handle_mobile_decision("/api/pending/9/discard", "s", token="s", decide=decide, body=body)
    assert seen[1] is None


def test_parse_review_edits_is_lenient() -> None:
    from grandplan.app.mobile_api import parse_review_edits

    assert parse_review_edits(b"") is None  # no body → no edits
    assert parse_review_edits(b"not json") is None  # garbled → no edits, never a crash
    assert parse_review_edits(b"{}") is None  # empty object → no usable field
    edits = parse_review_edits(b'{"title": "T", "tags": ["x", 3, "y"]}')  # 3 dropped (not a str)
    assert edits is not None and edits.title == "T" and edits.tags == ("x", "y")
    assert edits.body is None and edits.note_type is None
