"""Tests for the InMemoryNoteRepository (append-only + similarity search)."""

from __future__ import annotations

from grandplan.core.models import Edge, EdgeKind, Note, NoteEdit, NoteStatus, NoteType
from grandplan.core.repository import InMemoryNoteRepository


def _note(note_id: str) -> Note:
    return Note(id=note_id, original_id="o", title=note_id, body="b", type=NoteType.IDEA)


def test_add_note_is_append_only_and_idempotent() -> None:
    repo = InMemoryNoteRepository()
    note = _note("n1")
    repo.add_note(note, (1.0, 0.0))
    repo.add_note(note, (0.0, 1.0))  # ignored — append-only
    assert repo.get_note("n1") == note
    assert len(repo.notes()) == 1


def test_add_edge_deduplicates() -> None:
    repo = InMemoryNoteRepository()
    edge = Edge("a", "b", EdgeKind.RELATES)
    repo.add_edge(edge)
    repo.add_edge(edge)
    assert repo.edges() == (edge,)


def test_most_similar_orders_thresholds_and_limits() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("a"), (1.0, 0.0, 0.0))
    repo.add_note(_note("b"), (0.0, 1.0, 0.0))
    repo.add_note(_note("c"), (0.7, 0.7, 0.0))
    query = (1.0, 0.0, 0.0)

    assert [n.id for n, _ in repo.most_similar(query)] == ["a", "c", "b"]
    assert [n.id for n, _ in repo.most_similar(query, threshold=0.5)] == ["a", "c"]
    assert [n.id for n, _ in repo.most_similar(query, limit=1)] == ["a"]


def test_status_of_defaults_to_creation_status() -> None:
    # With no status event yet, the derived current status is the note's creation status.
    repo = InMemoryNoteRepository()
    repo.add_note(_note("n1"), (1.0,))  # _note() defaults to NoteStatus.INBOX
    assert repo.status_of("n1") is NoteStatus.INBOX


def test_set_status_overrides_without_mutating_the_note() -> None:
    # Event-sourced: a status event derives the current status; the stored note is never mutated.
    repo = InMemoryNoteRepository()
    repo.add_note(_note("n1"), (1.0,))
    repo.set_status("n1", NoteStatus.DONE)
    assert repo.status_of("n1") is NoteStatus.DONE
    note = repo.get_note("n1")
    assert note is not None and note.status is NoteStatus.INBOX  # lossless: creation status intact


def test_set_status_is_last_write_wins() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("n1"), (1.0,))
    repo.set_status("n1", NoteStatus.ACTIVE)
    repo.set_status("n1", NoteStatus.DONE)
    assert repo.status_of("n1") is NoteStatus.DONE


def test_status_of_unknown_note_is_none() -> None:
    assert InMemoryNoteRepository().status_of("missing") is None


# -- PR-C: edit events, derived current note, history -------------------------------------------


def test_set_status_to_the_current_status_records_no_event() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("n1"), (1.0,))  # creation status INBOX
    repo.set_status("n1", NoteStatus.INBOX)  # equals derived status → no-op
    repo.set_status("n1", NoteStatus.DONE)
    repo.set_status("n1", NoteStatus.DONE)  # idempotent: second changes nothing
    assert [e.status for e in repo.events()] == [NoteStatus.DONE]


def test_record_edit_derives_current_note_without_mutating_the_stored_note() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("n1"), (1.0,))
    repo.record_edit("n1", NoteEdit(title="renamed", due="2026-09-01"))

    current = repo.current_note("n1")
    assert current is not None
    assert current.title == "renamed" and current.due == "2026-09-01"
    assert current.id == "n1"  # identity stable
    stored = repo.get_note("n1")
    assert stored is not None and stored.title == "n1" and stored.due is None  # lossless


def test_edits_compose_in_order_last_write_wins_per_field() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("n1"), (1.0,))
    repo.record_edit("n1", NoteEdit(title="first", body="b1"))
    repo.record_edit("n1", NoteEdit(title="second"))  # only title changes again
    current = repo.current_note("n1")
    assert current is not None and current.title == "second" and current.body == "b1"


def test_current_note_carries_derived_status() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("n1"), (1.0,))
    repo.set_status("n1", NoteStatus.DONE)
    repo.record_edit("n1", NoteEdit(title="renamed"))
    current = repo.current_note("n1")
    assert current is not None and current.status is NoteStatus.DONE and current.title == "renamed"


def test_noop_edit_and_unknown_note_record_no_event() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("n1"), (1.0,))
    repo.record_edit("n1", NoteEdit())  # empty → no change
    repo.record_edit("n1", NoteEdit(title="n1"))  # same as current title → no change
    repo.record_edit("missing", NoteEdit(title="x"))  # unknown note → orphan-guarded
    assert repo.events() == ()


def test_history_and_events_are_ordered() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("n1"), (1.0,))
    repo.add_note(_note("n2"), (0.0, 1.0))
    repo.set_status("n1", NoteStatus.ACTIVE, at="t1")
    repo.record_edit("n1", NoteEdit(title="renamed"), at="t2")
    repo.set_status("n2", NoteStatus.DONE, at="t3")

    n1_history = repo.history_of("n1")
    assert [e.kind for e in n1_history] == ["status", "edit"]
    assert n1_history[0].at == "t1" and n1_history[1].at == "t2"
    assert [e.note_id for e in repo.events()] == ["n1", "n1", "n2"]  # global append order


def test_current_notes_returns_one_derived_note_per_stored_note() -> None:
    repo = InMemoryNoteRepository()
    repo.add_note(_note("n1"), (1.0,))
    repo.record_edit("n1", NoteEdit(title="renamed"))
    assert {n.id: n.title for n in repo.current_notes()} == {"n1": "renamed"}
