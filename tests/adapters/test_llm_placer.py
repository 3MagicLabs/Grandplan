"""Tests for the LlmPlacer adapter (prompt/parse/validation/fallback; client injected)."""

from __future__ import annotations

from grandplan.adapters.llm_placer import LlmPlacer, parse_placement
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Horizon, Note, NoteType, ProposedNote
from grandplan.core.placement import HeuristicPlacer, Placement
from grandplan.core.repository import InMemoryNoteRepository


def _proposed(title: str) -> ProposedNote:
    return ProposedNote(original_id="o", title=title, body=title, type=NoteType.TASK)


def _repo_with_goal() -> tuple[InMemoryNoteRepository, HashingEmbedder]:
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
    return repo, emb


def test_parse_placement_drops_hallucinated_and_self_referential_ids() -> None:
    placement = parse_placement('{"parent": "g", "depends_on": ["d1", "bogus", "g"]}', {"g", "d1"})
    assert placement.parent_id == "g"
    assert placement.depends_on == ("d1",)  # 'bogus' not a candidate; 'g' is the parent → dropped


def test_parse_placement_handles_null_parent_and_empty_deps() -> None:
    placement = parse_placement('{"parent": null, "depends_on": []}', {"g"})
    assert placement == Placement()


def test_parse_placement_parses_blocks_and_waiting_on() -> None:
    placement = parse_placement(
        '{"parent": null, "depends_on": ["a"], "blocks": ["b"], "waiting_on": ["c"]}',
        {"a", "b", "c"},
    )
    assert placement.depends_on == ("a",)
    assert placement.blocks == ("b",)
    assert placement.waiting_on == ("c",)


def test_parse_placement_gives_each_target_one_relation() -> None:
    # parent is excluded from all relations; an id used twice is kept only by the first relation.
    placement = parse_placement(
        '{"parent": "a", "depends_on": ["b"], "blocks": ["b", "c"], "waiting_on": ["a"]}',
        {"a", "b", "c"},
    )
    assert placement.parent_id == "a"
    assert placement.depends_on == ("b",)
    assert placement.blocks == ("c",)  # 'b' already claimed by depends_on
    assert placement.waiting_on == ()  # 'a' is the parent


def test_llm_placer_uses_valid_model_response() -> None:
    repo, emb = _repo_with_goal()
    placer = LlmPlacer(chat=lambda m, p: '{"parent": "g", "depends_on": []}')
    placement = placer.place(_proposed("launch checklist"), emb.embed("launch checklist"), repo)
    assert placement.parent_id == "g"


def test_llm_placer_falls_back_to_heuristic_on_bad_json() -> None:
    repo, emb = _repo_with_goal()
    placer = LlmPlacer(
        chat=lambda m, p: "not json at all", fallback=HeuristicPlacer(part_of_threshold=0.2)
    )
    placement = placer.place(
        _proposed("ship the analytics product launch checklist"),
        emb.embed("ship the analytics product launch checklist"),
        repo,
    )
    assert placement.parent_id == "g"  # heuristic fallback still placed it


def test_llm_placer_skips_the_model_when_no_candidates() -> None:
    def must_not_call(model: str, prompt: str) -> str:
        raise AssertionError("the model must not be called when there are no candidates")

    placer = LlmPlacer(chat=must_not_call)
    placement = placer.place(_proposed("x"), HashingEmbedder().embed("x"), InMemoryNoteRepository())
    assert placement == Placement()
