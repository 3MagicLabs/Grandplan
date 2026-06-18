"""Tests for the artifact-attach flow (core.attach.attach)."""

from __future__ import annotations

from grandplan.core.attach import attach
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Note, NoteType
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.resources import ResourceKind


def _repo() -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    embedder = HashingEmbedder()
    for note_id, title in (("r", "build the resume website"), ("t", "research trading strategies")):
        note = Note(
            id=note_id, original_id=f"o{note_id}", title=title, body=title, type=NoteType.TASK
        )
        repo.add_note(note, embedder.embed(title))
    return repo


def test_attach_matches_the_right_note_and_records_a_resource_event() -> None:
    repo = _repo()
    result = attach("/Users/me/resume-final.pdf", repo=repo, embedder=HashingEmbedder())

    assert result is not None
    assert result.note.id == "r"  # "resume final" matched the resume note, not the trading one
    assert result.resource.kind is ResourceKind.FILE
    assert repo.resources_of("r") == (result.resource,)  # attached as a derived resource


def test_description_overrides_the_match_text() -> None:
    repo = _repo()
    # A ref with no useful words on its own, steered to the trading note via --describe.
    result = attach(
        "https://x.io/a1b2", repo=repo, embedder=HashingEmbedder(), description="trading strategies"
    )
    assert result is not None and result.note.id == "t"
    assert result.resource.kind is ResourceKind.LINK


def test_no_confident_match_returns_none_and_attaches_nothing() -> None:
    repo = _repo()
    result = attach("/tmp/unrelated-zebra-photo.png", repo=repo, embedder=HashingEmbedder())
    assert result is None
    assert repo.resources_of("r") == () and repo.resources_of("t") == ()


def test_ref_with_no_usable_words_returns_none() -> None:
    # A ref that describes to nothing (and no --describe) can't be matched → None.
    assert attach("///", repo=_repo(), embedder=HashingEmbedder()) is None
