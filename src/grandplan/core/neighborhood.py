"""A note's place in the graph: everything connected to it, both directions (SPEC-ACT §A2).

`VaultQuery.get_note` reports a note's links, but only the **outgoing** ones (`edge.source_id ==
note_id`). That is fine for rendering a note's own "Links" section and wrong for *navigation*:
`apply_plan_draft` writes `plan --builds_on--> source`, so a source idea's connection to the plan
built on it exists only as an incoming edge. Ask that note what it's connected to and the answer is
"nothing" — while it is in fact a hub.

This module answers the navigation question instead: given a note, which notes touch it, by what
kind of edge, and in which direction. Pure functions over the repository; the visual side stays
Obsidian's local-graph pane (it already does depth and layout better than a terminal can).
"""

from __future__ import annotations

from dataclasses import dataclass

from grandplan.core.models import EdgeKind, Note
from grandplan.core.ports import NoteRepository


@dataclass(frozen=True)
class Link:
    """One connection to a neighbouring note.

    `outgoing` is True when *this* note points at `other`, False when `other` points at this one.
    The distinction is the difference between "I depend on X" and "X depends on me".
    """

    kind: EdgeKind
    other: Note
    outgoing: bool


@dataclass(frozen=True)
class Neighborhood:
    """A note plus every note directly connected to it (depth 1, both directions)."""

    note: Note
    links: tuple[Link, ...]


def build_neighborhood(repo: NoteRepository, note_id: str) -> Neighborhood | None:
    """Every note directly connected to `note_id`, in either direction. None when unknown.

    Edges pointing at a note that no longer exists are skipped rather than raising: a dangling edge
    is a `doctor` finding, and navigation should still work in a vault that has one.
    """
    note = repo.current_note(note_id) or repo.get_note(note_id)
    if note is None:
        return None
    by_id = {n.id: n for n in repo.current_notes()}
    links: list[Link] = []
    for edge in repo.edges():
        if edge.source_id == note_id:
            other = by_id.get(edge.target_id)
            outgoing = True
        elif edge.target_id == note_id:
            other = by_id.get(edge.source_id)
            outgoing = False
        else:
            continue
        if other is not None and other.id != note_id:  # skip dangling edges and self-loops
            links.append(Link(kind=edge.kind, other=other, outgoing=outgoing))
    # Title-then-id ordering keeps the view stable across re-projections (same rule as the planner).
    links.sort(key=lambda link: (link.other.title, link.other.id, link.kind.value))
    return Neighborhood(note=note, links=tuple(links))


def render_neighborhood(nb: Neighborhood) -> str:
    """The terminal view of a note's graph position: what it points at, and what points at it."""
    header = f"{nb.note.title}  [{nb.note.id}]  ({nb.note.type.value})"
    if not nb.links:
        return (
            f"{header}\n\n"
            "No links — this note is an orphan in the graph.\n"
            "Obsidian hides orphans in the graph view unless Settings → Graph → Filters → "
            '"Show orphans" is on, so an orphan-heavy vault looks far smaller than its note count.\n'
            "To connect it: `grandplan relink -o <vault>` adds missing links between existing notes."
        )
    lines = "\n".join(
        f"  {'→' if link.outgoing else '←'} {link.kind.value:<12} "
        f"{link.other.title}  [{link.other.id}]  ({link.other.type.value})"
        for link in nb.links
    )
    return (
        f"{header}\n\nConnected notes ({len(nb.links)}):\n{lines}\n\n"
        "(→ this note points at it;  ← it points at this note)"
    )
