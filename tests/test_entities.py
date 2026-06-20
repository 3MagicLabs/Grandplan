"""Tests for entity extraction — heuristic extractor + append-only `involves` materialization."""

from __future__ import annotations

from grandplan.core.embed import HashingEmbedder
from grandplan.core.entities import (
    EntityMention,
    HeuristicEntityExtractor,
    entity_note,
    materialize_entities,
)
from grandplan.core.models import EdgeKind, Note, NoteType, Original, Source
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore


def _extract(text: str) -> set[str]:
    return {m.name for m in HeuristicEntityExtractor().extract(text)}


def test_extracts_multi_word_proper_noun() -> None:
    assert "Sarah Chen" in _extract("ping Sarah Chen about the deck")


def test_extracts_org_suffix_name() -> None:
    assert "Anthropic Labs" in _extract("the Anthropic Labs partnership")


def test_extracts_handle() -> None:
    assert "@maria" in _extract("@maria owns the rollout")


def test_ignores_single_sentence_initial_capital() -> None:
    # "Build" starts the sentence but is not a multi-word proper noun → not an entity.
    assert _extract("Build the offline capture popup") == set()


def test_extraction_is_deduped_case_insensitively_and_order_stable() -> None:
    mentions = HeuristicEntityExtractor().extract("Sarah Chen met Sarah Chen and John Doe")
    names = [m.name for m in mentions]
    assert names == ["Sarah Chen", "John Doe"]


def test_entity_note_id_is_stable_by_name() -> None:
    _, a = entity_note("Sarah Chen")
    _, b = entity_note("Sarah Chen")
    assert a.id == b.id and a.type is NoteType.ENTITY


def _repo_with_source() -> tuple[InMemoryNoteRepository, InMemoryOriginalStore, HashingEmbedder]:
    repo, originals, emb = InMemoryNoteRepository(), InMemoryOriginalStore(), HashingEmbedder()
    originals.add(Original(id="o1", text="ping Sarah Chen", source=Source(app="t"), created="2026"))
    note = Note(id="s", original_id="o1", title="ping Sarah Chen", body="", type=NoteType.TASK)
    repo.add_note(note, emb.embed(note.title))
    return repo, originals, emb


def test_materialize_creates_entity_and_involves_edge() -> None:
    repo, originals, emb = _repo_with_source()
    ids = materialize_entities(repo, originals, emb, "s", (EntityMention("Sarah Chen"),))
    assert len(ids) == 1
    entity = repo.get_note(ids[0])
    assert entity is not None and entity.type is NoteType.ENTITY
    assert any(
        e.source_id == "s" and e.target_id == ids[0] and e.kind is EdgeKind.INVOLVES
        for e in repo.edges()
    )


def test_materialize_is_idempotent() -> None:
    repo, originals, emb = _repo_with_source()
    materialize_entities(repo, originals, emb, "s", (EntityMention("Sarah Chen"),))
    edges_before = len(repo.edges())
    materialize_entities(repo, originals, emb, "s", (EntityMention("Sarah Chen"),))
    assert len(repo.edges()) == edges_before  # same entity → no duplicate node/edge


def test_materialize_unknown_source_is_noop() -> None:
    repo, originals, emb = _repo_with_source()
    assert materialize_entities(repo, originals, emb, "nope", (EntityMention("Sarah Chen"),)) == ()


def test_materialize_dedupes_repeated_mentions_in_one_call() -> None:
    repo, originals, emb = _repo_with_source()
    ids = materialize_entities(
        repo,
        originals,
        emb,
        "s",
        (EntityMention("Sarah Chen"), EntityMention("Sarah Chen")),
    )
    assert len(ids) == 1  # the second identical mention is skipped
