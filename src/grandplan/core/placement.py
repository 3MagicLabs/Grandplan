"""Placement — fit a new note into the existing graph's structure (PR-G, the keystone).

The reconciler links notes by *similarity* (`relates`); the planner needs *structural* edges to
build a hierarchy and a dependency order. This stage proposes them: a **parent** the note belongs
under (`part_of`) and the **prerequisites** it waits on (`depends_on`). It is a Strategy behind the
`Placer` port (ADR-0003/0007): the deterministic `HeuristicPlacer` is the offline default; a richer
`LlmPlacer` (adapters) proposes the same shape with a deterministic fallback.

Append-only & safe (ADR-0008): placement only ever *adds typed edges* — no stored note is mutated,
no note id changes — and an edge is recorded only to a real existing note (no broken edges).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from grandplan.core.models import Edge, EdgeKind, Horizon, ProposedNote
from grandplan.core.ports import NoteRepository

# Altitude rank: lower = more abstract. A note is `part_of` a note that is strictly MORE abstract.
_HORIZON_RANK: dict[Horizon, int] = {
    Horizon.MASTERPLAN: 0,
    Horizon.GOAL: 1,
    Horizon.PROJECT: 2,
    Horizon.ACTION: 3,
}

_DEFAULT_PART_OF_THRESHOLD = (
    0.35  # above the reconciler's link threshold (0.30): a real "belongs to"
)
_DEFAULT_CANDIDATES = 8  # how many most-similar existing notes a Placer considers


@dataclass(frozen=True)
class Placement:
    """How a new note fits the graph: a parent it is part of, and prerequisites it depends on."""

    parent_id: str | None = None
    depends_on: tuple[str, ...] = ()

    def edges(self, note_id: str) -> tuple[Edge, ...]:
        """The typed structural edges to record for the new note (new → existing)."""
        out: list[Edge] = []
        if self.parent_id is not None and self.parent_id != note_id:
            out.append(Edge(note_id, self.parent_id, EdgeKind.PART_OF))
        for dep in self.depends_on:
            if dep != note_id and dep != self.parent_id:
                out.append(Edge(note_id, dep, EdgeKind.DEPENDS_ON))
        return tuple(out)


class Placer(Protocol):
    """Propose how a new proposed note fits into the existing graph (Strategy)."""

    def place(
        self, proposed: ProposedNote, embedding: tuple[float, ...], repo: NoteRepository
    ) -> Placement: ...


def record_placement(repo: NoteRepository, placement: Placement | None, note_id: str) -> None:
    """Add a placement's structural edges, guarded so only edges to real existing notes are written
    (no broken edges, append-only). A no-op when there's nothing to place."""
    if placement is None:
        return
    for edge in placement.edges(note_id):
        if repo.get_note(edge.target_id) is not None:
            repo.add_edge(edge)


class HeuristicPlacer:
    """Deterministic offline placer: attach a note under the most-similar MORE-ABSTRACT note.

    `part_of` only — a task/idea attaches to the most-similar project or goal, a project to the
    most-similar goal, etc. Dependency order can't be inferred reliably without understanding the
    content, so `depends_on` is left to the LLM placer (this baseline returns none).
    """

    def __init__(
        self,
        *,
        part_of_threshold: float = _DEFAULT_PART_OF_THRESHOLD,
        candidates: int = _DEFAULT_CANDIDATES,
    ) -> None:
        self._threshold = part_of_threshold
        self._candidates = candidates

    def place(
        self, proposed: ProposedNote, embedding: tuple[float, ...], repo: NoteRepository
    ) -> Placement:
        new_rank = _HORIZON_RANK[proposed.horizon]
        ranked = repo.most_similar(embedding, limit=self._candidates, threshold=self._threshold)
        for note, _score in ranked:  # most-similar first
            if _HORIZON_RANK[note.horizon] < new_rank:  # strictly more abstract → a valid parent
                return Placement(parent_id=note.id)
        return Placement()
