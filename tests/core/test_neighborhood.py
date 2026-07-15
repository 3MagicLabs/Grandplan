"""Tests for the graph neighborhood — a note's place in the graph and everything connected to it.

The load-bearing property is **bidirectionality**: `VaultQuery.get_note` reports only outgoing
edges, which is why a note could never see what pointed *at* it (SPEC-ACT §A2).
"""

from __future__ import annotations

from grandplan.core.models import Edge, EdgeKind, Note, NoteType
from grandplan.core.neighborhood import build_neighborhood, render_neighborhood
from grandplan.core.repository import InMemoryNoteRepository


def _note(nid: str, title: str) -> Note:
    return Note(id=nid, original_id=f"o{nid}", title=title, body="b", type=NoteType.TASK)


def _repo(notes: list[Note], edges: list[Edge]) -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    for note in notes:
        repo.add_note(note, (1.0,))
    for edge in edges:
        repo.add_edge(edge)
    return repo


def test_neighborhood_includes_outgoing_links() -> None:
    repo = _repo(
        [_note("a", "Alpha"), _note("b", "Beta")],
        [Edge("a", "b", EdgeKind.DEPENDS_ON)],
    )
    nb = build_neighborhood(repo, "a")
    assert nb is not None
    assert [(link.other.id, link.outgoing) for link in nb.links] == [("b", True)]


def test_neighborhood_includes_incoming_links() -> None:
    # THE bug this module exists for: `apply_plan_draft` writes `plan --builds_on--> source`, so a
    # source note's only connection to the plan built on it is an INCOMING edge. Outgoing-only means
    # the source looks like an orphan while actually being a hub.
    repo = _repo(
        [_note("p", "Q3 Plan"), _note("s", "Source idea")],
        [Edge("p", "s", EdgeKind.BUILDS_ON)],
    )
    nb = build_neighborhood(repo, "s")
    assert nb is not None
    assert [(link.other.id, link.outgoing) for link in nb.links] == [("p", False)]


def test_neighborhood_reports_both_directions_together() -> None:
    repo = _repo(
        [_note("a", "Alpha"), _note("b", "Beta"), _note("c", "Gamma")],
        [Edge("a", "b", EdgeKind.DEPENDS_ON), Edge("c", "a", EdgeKind.BUILDS_ON)],
    )
    nb = build_neighborhood(repo, "a")
    assert nb is not None
    assert {(link.other.id, link.outgoing) for link in nb.links} == {("b", True), ("c", False)}


def test_neighborhood_of_unknown_note_is_none() -> None:
    assert build_neighborhood(_repo([], []), "nope") is None


def test_neighborhood_skips_edges_to_notes_that_no_longer_exist() -> None:
    # A dangling edge must not crash navigation — it is a doctor finding, not a hard error here.
    repo = _repo([_note("a", "Alpha")], [Edge("a", "ghost", EdgeKind.RELATES)])
    nb = build_neighborhood(repo, "a")
    assert nb is not None
    assert nb.links == ()


def test_neighborhood_links_are_deterministically_ordered() -> None:
    repo = _repo(
        [_note("a", "Alpha"), _note("b", "Beta"), _note("c", "Gamma")],
        [Edge("a", "c", EdgeKind.RELATES), Edge("a", "b", EdgeKind.RELATES)],
    )
    first = [link.other.id for link in build_neighborhood(repo, "a").links]  # type: ignore[union-attr]
    second = [link.other.id for link in build_neighborhood(repo, "a").links]  # type: ignore[union-attr]
    assert first == second == ["b", "c"]  # by title, stable across re-projections


def test_render_shows_direction_and_kind() -> None:
    repo = _repo(
        [_note("a", "Alpha"), _note("b", "Beta"), _note("c", "Gamma")],
        [Edge("a", "b", EdgeKind.DEPENDS_ON), Edge("c", "a", EdgeKind.BUILDS_ON)],
    )
    text = render_neighborhood(build_neighborhood(repo, "a"))  # type: ignore[arg-type]
    assert "Alpha" in text
    assert "depends_on" in text and "Beta" in text
    assert "builds_on" in text and "Gamma" in text
    assert "→" in text and "←" in text  # both directions are visually distinguishable


def test_render_of_an_orphan_explains_the_obsidian_show_orphans_setting() -> None:
    # An orphan is invisible in Obsidian's graph unless "Show orphans" is on — the single most
    # common reason a vault's graph looks smaller than the note count.
    text = render_neighborhood(build_neighborhood(_repo([_note("a", "Alpha")], []), "a"))  # type: ignore[arg-type]
    assert "orphan" in text.lower()
    assert "show orphans" in text.lower()
