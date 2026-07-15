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


# -- capture-component wiring (fast capture) ------------------------------------------------------
# Measured on the 16 GB no-GPU target: one capture under --llm makes 3 sequential model calls
# (organize + contextual reconcile + placement) at ~8-15 s each — ~25-45 s before the review dialog
# appears. Fast mode keeps the ONE call that produces the note (LLM organize) and swaps the two
# enrichment calls for their instant deterministic baselines (~3× faster per capture).


def test_capture_components_default_llm_wires_all_the_llm_adapters() -> None:
    from grandplan.adapters.llm_contextual_reconciler import LlmContextualReconciler
    from grandplan.adapters.llm_entity_extractor import LlmEntityExtractor
    from grandplan.adapters.llm_placer import LlmPlacer
    from grandplan.adapters.ollama_organizer import OllamaOrganizer
    from grandplan.app.gui import _capture_components

    organizer, reconciler, placer, entities = _capture_components(
        use_llm=True, fast=False, model="m"
    )
    assert isinstance(organizer, OllamaOrganizer)
    assert isinstance(reconciler, LlmContextualReconciler)
    assert isinstance(placer, LlmPlacer)
    assert isinstance(entities, LlmEntityExtractor)


def test_capture_components_fast_keeps_llm_organize_but_heuristic_links_and_placement() -> None:
    # --fast: the model still organizes the note (that's the product); links + placement fall back
    # to the deterministic baselines so they cost ~0 on the capture's critical path.
    from grandplan.adapters.ollama_organizer import OllamaOrganizer
    from grandplan.app.gui import _capture_components
    from grandplan.core.placement import HeuristicPlacer
    from grandplan.core.reconcile import SimilarityReconciler

    organizer, reconciler, placer, _entities = _capture_components(
        use_llm=True, fast=True, model="m"
    )
    assert isinstance(organizer, OllamaOrganizer)
    assert isinstance(reconciler, SimilarityReconciler)
    assert isinstance(placer, HeuristicPlacer)


def test_capture_components_always_wire_an_entity_extractor() -> None:
    # The people/org graph must build on EVERY capture path, including --fast and --no-llm. The
    # heuristic extractor is pure Python, so it costs no model call — there is no budget reason to
    # ever leave capture without one, and without one a hotkey/phone capture builds no graph at all.
    from grandplan.app.gui import _capture_components
    from grandplan.core.entities import HeuristicEntityExtractor

    for use_llm, fast in ((False, False), (False, True), (True, True)):
        _o, _r, _p, entities = _capture_components(use_llm=use_llm, fast=fast, model="m")
        assert isinstance(entities, HeuristicEntityExtractor), (use_llm, fast)


def test_capture_components_no_llm_is_fully_deterministic_regardless_of_fast() -> None:
    # --no-llm already makes zero model calls; --fast must not change (or break) that baseline.
    from grandplan.app.gui import _capture_components
    from grandplan.core.entities import HeuristicEntityExtractor
    from grandplan.core.organize import HeuristicOrganizer
    from grandplan.core.placement import HeuristicPlacer
    from grandplan.core.reconcile import SimilarityReconciler

    for fast in (False, True):
        organizer, reconciler, placer, entities = _capture_components(
            use_llm=False, fast=fast, model="m"
        )
        assert isinstance(organizer, HeuristicOrganizer)
        assert isinstance(reconciler, SimilarityReconciler)
        assert isinstance(placer, HeuristicPlacer)
        assert isinstance(entities, HeuristicEntityExtractor)


def test_reachable_ipv4s_drops_loopback_and_link_local() -> None:
    # The phone-app banner must never print the bind address / an unreachable interface: loopback
    # (127.*) and APIPA link-local (169.254.*, a disconnected/unassigned NIC) are filtered; real LAN
    # + Tailscale addresses survive, deduped and sorted.
    from grandplan.app.gui import _reachable_ipv4s

    got = _reachable_ipv4s(
        ["127.0.0.1", "169.254.83.107", "192.168.1.237", "100.64.0.5", "192.168.1.237"]
    )
    assert got == ["100.64.0.5", "192.168.1.237"]
    assert _reachable_ipv4s(["127.0.0.1", "169.254.1.1"]) == []  # nothing reachable → empty


def test_is_bind_all_host_detects_unroutable_bind_addresses() -> None:
    # The banner shows real IPs only when bound to "all interfaces" (which a phone can't dial).
    from grandplan.app.gui import _is_bind_all_host

    assert _is_bind_all_host("0.0.0.0") is True
    assert _is_bind_all_host("") is True
    assert _is_bind_all_host("::") is True
    assert _is_bind_all_host("192.168.1.237") is False  # a real LAN IP → dialable, print as-is
    assert _is_bind_all_host("100.64.0.5") is False  # Tailscale IP → dialable
