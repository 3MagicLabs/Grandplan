"""Tests for the structural placement stage (PR-G) — the deterministic HeuristicPlacer."""

from __future__ import annotations

from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Horizon, Note, NoteType, ProposedNote
from grandplan.core.placement import HeuristicPlacer, Placement
from grandplan.core.repository import InMemoryNoteRepository


def _proposed(
    title: str, *, type_: NoteType = NoteType.TASK, horizon: Horizon = Horizon.ACTION
) -> ProposedNote:
    return ProposedNote(original_id="o", title=title, body=title, type=type_, horizon=horizon)


def test_placement_edges_builds_part_of_and_depends_on() -> None:
    edges = Placement(parent_id="g", depends_on=("d1", "d2")).edges("n")
    kinds = {(e.target_id, e.kind.value) for e in edges}
    assert ("g", "part_of") in kinds
    assert ("d1", "depends_on") in kinds and ("d2", "depends_on") in kinds


def test_placement_edges_excludes_self_and_parent_as_dependency() -> None:
    # parent==self is dropped; a dependency equal to self or to the parent is dropped.
    edges = Placement(parent_id="g", depends_on=("n", "g", "d")).edges("n")
    targets = [e.target_id for e in edges]
    assert "n" not in targets  # never an edge to itself
    assert targets.count("g") == 1  # g is the parent, not also a dependency
    assert "d" in targets


def test_heuristic_placer_attaches_to_more_abstract_similar_note() -> None:
    repo = InMemoryNoteRepository()
    emb = HashingEmbedder()
    goal = Note(
        id="g",
        original_id="og",
        title="ship the analytics product roadmap",
        body="b",
        type=NoteType.GOAL,
        horizon=Horizon.GOAL,
    )
    repo.add_note(goal, emb.embed("ship the analytics product roadmap"))

    proposed = _proposed("ship the analytics product launch checklist")
    placement = HeuristicPlacer(part_of_threshold=0.2).place(
        proposed, emb.embed("ship the analytics product launch checklist"), repo
    )
    assert placement.parent_id == "g"  # an action attaches under the similar, more-abstract goal
    assert placement.depends_on == ()  # heuristic leaves dependency inference to the LLM


def test_heuristic_placer_ignores_same_abstraction_note() -> None:
    repo = InMemoryNoteRepository()
    emb = HashingEmbedder()
    sibling = Note(
        id="a",
        original_id="oa",
        title="ship the analytics product launch checklist",
        body="b",
        type=NoteType.TASK,  # ACTION horizon: same rank as the new note → not a parent
    )
    repo.add_note(sibling, emb.embed("ship the analytics product launch checklist"))

    proposed = _proposed("ship the analytics product launch checklist now")
    placement = HeuristicPlacer(part_of_threshold=0.2).place(
        proposed, emb.embed("ship the analytics product launch checklist now"), repo
    )
    assert placement.parent_id is None


def test_heuristic_placer_below_threshold_returns_empty() -> None:
    repo = InMemoryNoteRepository()
    emb = HashingEmbedder()
    goal = Note(
        id="g",
        original_id="og",
        title="unrelated cooking recipe",
        body="b",
        type=NoteType.GOAL,
        horizon=Horizon.GOAL,
    )
    repo.add_note(goal, emb.embed("unrelated cooking recipe"))

    placement = HeuristicPlacer(part_of_threshold=0.99).place(
        _proposed("quarterly tax filing"), emb.embed("quarterly tax filing"), repo
    )
    assert placement == Placement()
