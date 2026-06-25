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


def test_corner_position_places_bottom_right_within_area() -> None:
    from grandplan.app.gui import _corner_position

    x, y = _corner_position(340, 120, 0, 0, 1920, 1080, margin=24)
    assert x == 1920 - 340 - 24
    assert y == 1080 - 120 - 24


def test_corner_position_respects_area_offset() -> None:
    from grandplan.app.gui import _corner_position

    # A non-primary screen whose work-area starts at (100, 200).
    x, y = _corner_position(100, 50, 100, 200, 800, 600, margin=10)
    assert x == 100 + 800 - 100 - 10
    assert y == 200 + 600 - 50 - 10


def test_corner_position_clamps_oversized_popup_onto_screen() -> None:
    from grandplan.app.gui import _corner_position

    # A popup larger than the area must not be pushed off the top-left edge.
    assert _corner_position(3000, 3000, 0, 0, 1920, 1080) == (0, 0)


def test_bounded_size_caps_to_screen_fraction() -> None:
    from grandplan.app.gui import _bounded_size

    # Content far bigger than the screen → capped to the fraction, never the full display.
    w, h = _bounded_size(10_000, 10_000, 1920, 1080)
    assert w == int(1920 * 0.55) and h == int(1080 * 0.75)
    assert w < 1920 and h < 1080


def test_bounded_size_enforces_a_minimum_for_tiny_content() -> None:
    from grandplan.app.gui import _bounded_size

    assert _bounded_size(120, 90, 1920, 1080) == (360, 240)  # bumped up to the minimums


def test_bounded_size_passes_through_mid_range_content() -> None:
    from grandplan.app.gui import _bounded_size

    assert _bounded_size(560, 480, 1920, 1080) == (560, 480)


def test_centered_position_centers_within_area() -> None:
    from grandplan.app.gui import _centered_position

    assert _centered_position(400, 300, 0, 0, 1920, 1080) == ((1920 - 400) // 2, (1080 - 300) // 2)
