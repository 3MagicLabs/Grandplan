"""Tests for Note / Edge / ProposedNote domain models."""

from __future__ import annotations

from grandplan.core.models import Edge, EdgeKind, Horizon, Note, NoteType, ProposedNote


def _proposed(title: str = "Idea", body: str = "body", original_id: str = "orig") -> ProposedNote:
    return ProposedNote(original_id=original_id, title=title, body=body, type=NoteType.IDEA)


def test_from_proposed_is_deterministic() -> None:
    a = Note.from_proposed(_proposed())
    b = Note.from_proposed(_proposed())
    assert a == b
    assert len(a.id) == 16


def test_from_proposed_differs_on_content() -> None:
    assert Note.from_proposed(_proposed(title="One")) != Note.from_proposed(_proposed(title="Two"))


def test_from_proposed_carries_fields() -> None:
    note = Note.from_proposed(_proposed())
    assert note.original_id == "orig"
    assert note.type is NoteType.IDEA
    assert note.status.value == "inbox"
    assert note.horizon is Horizon.ACTION


def test_edge_is_hashable_and_equal() -> None:
    e1 = Edge("a", "b", EdgeKind.DEPENDS_ON)
    e2 = Edge("a", "b", EdgeKind.DEPENDS_ON)
    assert e1 == e2
    assert len({e1, e2}) == 1
