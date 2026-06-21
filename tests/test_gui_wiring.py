"""Hermetic tests for app.gui data wiring that needs no Qt.

The Qt dialog/threading is `pragma: no cover` and only runs on Windows, but the plain-Python
data structures it relies on ARE testable here — and a gap in that coverage let a real runtime
crash through (a non-frozen dataclass is unhashable, so the worker's `pending_reviews` set blew
up with TypeError on the first capture). These tests pin that contract.
"""

from __future__ import annotations

from grandplan.app.gui import _ReviewRequest
from grandplan.app.review import ReviewState


def _state() -> ReviewState:
    return ReviewState(
        original_text="x",
        title="t",
        note_type="idea",
        tags=(),
        related_titles=(),
        is_probable_duplicate=False,
    )


def test_review_request_is_hashable_and_usable_in_a_set() -> None:
    # Regression: gui.run_app tracks in-flight reviews in `pending_reviews: set[_ReviewRequest]`
    # so quit can release a blocked worker. A non-frozen dataclass is unhashable by default →
    # `set.add` raised TypeError at runtime. Identity semantics (eq=False) fix it without freezing
    # the mutable `approved` field the main thread writes.
    request = _ReviewRequest(state=_state())
    pending: set[_ReviewRequest] = set()
    pending.add(request)  # must not raise
    assert request in pending
    pending.discard(request)
    assert request not in pending


def test_review_requests_are_distinct_by_identity() -> None:
    # Two requests with equal content are still distinct entries (identity, not value, equality).
    pending = {_ReviewRequest(state=_state()), _ReviewRequest(state=_state())}
    assert len(pending) == 2


def test_review_request_defaults_to_not_approved() -> None:
    # On quit we set the event without setting approved → it must default to a discard (False).
    assert _ReviewRequest(state=_state()).approved is False


def test_clip_bounds_popup_label_length_and_collapses_whitespace() -> None:
    from grandplan.app.gui import _clip

    assert _clip("short title", 90) == "short title"  # under the limit → unchanged
    long = "x" * 200
    clipped = _clip(long, 90)
    assert len(clipped) == 90 and clipped.endswith("…")  # bounded so the popup can't blow up
    assert (
        _clip("line one\nline two", 90) == "line one line two"
    )  # newlines collapsed (no tall popup)
