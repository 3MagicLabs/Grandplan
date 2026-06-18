"""Tests for Note / Edge / ProposedNote domain models."""

from __future__ import annotations

from grandplan.core.models import (
    Edge,
    EdgeKind,
    Horizon,
    Note,
    NoteEdit,
    NoteEvent,
    NoteStatus,
    NoteType,
    ProposedNote,
    apply_edit,
    default_horizon,
)


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


def test_from_proposed_carries_resources_without_changing_the_id() -> None:
    from grandplan.core.resources import Resource, ResourceKind

    resources = (Resource(ResourceKind.LINK, "https://example.com"),)
    plain = Note.from_proposed(_proposed())
    with_res = Note.from_proposed(
        ProposedNote(
            original_id="orig", title="Idea", body="body", type=NoteType.IDEA, resources=resources
        )
    )
    assert with_res.resources == resources
    assert with_res.id == plain.id  # resources are not part of the content-addressed identity


def test_default_horizon_follows_type() -> None:
    assert default_horizon(NoteType.GOAL) is Horizon.GOAL
    assert default_horizon(NoteType.PROJECT) is Horizon.PROJECT
    assert default_horizon(NoteType.TASK) is Horizon.ACTION
    assert default_horizon(NoteType.IDEA) is Horizon.ACTION


def test_edge_is_hashable_and_equal() -> None:
    e1 = Edge("a", "b", EdgeKind.DEPENDS_ON)
    e2 = Edge("a", "b", EdgeKind.DEPENDS_ON)
    assert e1 == e2
    assert len({e1, e2}) == 1


# -- PR-C: edits + history ----------------------------------------------------------------------


def _note(**over: object) -> Note:
    base = dict(
        id="abc123",
        original_id="orig",
        title="Build the resume",
        body="a body",
        type=NoteType.TASK,
        tags=("career",),
        due=None,
    )
    base.update(over)
    return Note(**base)  # type: ignore[arg-type]


def test_apply_edit_changes_set_fields_and_keeps_the_id_stable() -> None:
    edited = apply_edit(_note(), NoteEdit(title="Build the CV", due="2026-09-01"))
    assert edited.title == "Build the CV"
    assert edited.due == "2026-09-01"
    assert edited.body == "a body"  # unchanged field preserved
    assert edited.tags == ("career",)  # unchanged field preserved
    assert edited.id == "abc123"  # identity is stable across an edit (NOT recomputed)


def test_apply_edit_replaces_tags_wholesale() -> None:
    edited = apply_edit(_note(), NoteEdit(tags=("cv", "job-search")))
    assert edited.tags == ("cv", "job-search")


def test_apply_empty_edit_is_a_noop() -> None:
    note = _note()
    assert NoteEdit().is_empty()
    assert apply_edit(note, NoteEdit()) == note


def test_note_event_summary_reads_naturally() -> None:
    status_event = NoteEvent(note_id="abc123", kind="status", at="t", status=NoteStatus.DONE)
    edit_event = NoteEvent(
        note_id="abc123", kind="edit", at="t", edit=NoteEdit(due="Q3", title="New")
    )
    assert status_event.summary() == "status → done"
    assert "due → Q3" in edit_event.summary()
    assert "title → New" in edit_event.summary()
