"""Tests for JsonlNoteRepository — the persistent, rehydrating note index.

The GUI keeps an index in memory; without persistence a restart would forget every prior note,
so new captures could never link to history (US-5). This store mirrors the JsonlOriginalStore
pattern: append-only, idempotent, and lossless across a reopen.
"""

from __future__ import annotations

from pathlib import Path

from grandplan.core.models import Edge, EdgeKind, Note, NoteEdit, NoteStatus, NoteType
from grandplan.core.note_store import JsonlNoteRepository
from grandplan.core.resources import Resource, ResourceKind


def _note(note_id: str, title: str) -> Note:
    return Note(
        id=note_id,
        original_id=f"orig-{note_id}",
        title=title,
        body=f"body of {title}",
        type=NoteType.TASK,
        status=NoteStatus.NEXT,
        tags=("alpha", "beta"),
    )


def test_persists_notes_embeddings_and_edges_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / ".grandplan" / "index.jsonl"
    repo = JsonlNoteRepository(path)
    a, b = _note("a1", "First"), _note("b2", "Second")
    repo.add_note(a, (1.0, 0.0))
    repo.add_note(b, (0.0, 1.0))
    repo.add_edge(Edge("b2", "a1", EdgeKind.RELATES))

    # Reopen: a fresh instance must rehydrate everything from disk.
    reopened = JsonlNoteRepository(path)
    assert reopened.get_note("a1") == a
    assert reopened.get_note("b2") == b
    assert set(reopened.edges()) == {Edge("b2", "a1", EdgeKind.RELATES)}
    top = reopened.most_similar((1.0, 0.0), limit=1, threshold=0.5)
    assert top and top[0][0].id == "a1"


def test_append_only_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "index.jsonl"
    repo = JsonlNoteRepository(path)
    a = _note("a1", "First")
    repo.add_note(a, (1.0, 0.0))
    repo.add_note(a, (1.0, 0.0))  # idempotent on identical id
    repo.add_edge(Edge("a1", "a1", EdgeKind.RELATES))
    repo.add_edge(Edge("a1", "a1", EdgeKind.RELATES))  # idempotent
    reopened = JsonlNoteRepository(path)
    assert len(reopened.notes()) == 1
    assert len(reopened.edges()) == 1


def test_note_resources_round_trip_and_old_records_default_empty(tmp_path: Path) -> None:
    # PR-D: a note's resources persist and rehydrate; a pre-PR-D record (no key) loads as ().
    path = tmp_path / "index.jsonl"
    repo = JsonlNoteRepository(path)
    note = Note(
        id="r1",
        original_id="o",
        title="With links",
        body="b",
        type=NoteType.IDEA,
        resources=(
            Resource(ResourceKind.LINK, "https://example.com", "site"),
            Resource(ResourceKind.PLACEHOLDER, "resume"),
        ),
    )
    repo.add_note(note, (1.0,))
    assert JsonlNoteRepository(path).get_note("r1") == note  # full round-trip incl. resources

    # A legacy note record without the "resources" key still loads (→ empty), proving back-compat.
    legacy = path.parent / "legacy.jsonl"
    legacy.write_text(
        '{"kind":"note","note":{"id":"x","original_id":"o","title":"t","body":"b",'
        '"type":"idea","status":"inbox","horizon":"action"},"embedding":[1.0]}\n',
        encoding="utf-8",
    )
    loaded = JsonlNoteRepository(legacy).get_note("x")
    assert loaded is not None and loaded.resources == ()


def test_creates_missing_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "vault" / ".grandplan" / "index.jsonl"
    JsonlNoteRepository(path).add_note(_note("a1", "First"), (1.0, 0.0))
    assert path.exists()


def test_status_event_overrides_creation_status_and_rehydrates(tmp_path: Path) -> None:
    # PR-A (ADR-0008): a status change is an appended event, not a mutation; current state is
    # derived. A fresh instance must replay the log and recover the derived status.
    path = tmp_path / "index.jsonl"
    repo = JsonlNoteRepository(path)
    repo.add_note(_note("a1", "First"), (1.0, 0.0))  # _note() creation status is NEXT
    repo.set_status("a1", NoteStatus.DONE)

    assert repo.status_of("a1") is NoteStatus.DONE
    note = repo.get_note("a1")
    assert note is not None and note.status is NoteStatus.NEXT  # stored note untouched (lossless)

    reopened = JsonlNoteRepository(path)
    assert reopened.status_of("a1") is NoteStatus.DONE  # derived status survives a reopen


def test_status_events_are_last_write_wins_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "index.jsonl"
    repo = JsonlNoteRepository(path)
    repo.add_note(_note("a1", "First"), (1.0, 0.0))
    repo.set_status("a1", NoteStatus.ACTIVE)
    repo.set_status("a1", NoteStatus.DONE)
    assert JsonlNoteRepository(path).status_of("a1") is NoteStatus.DONE


def test_recording_unchanged_status_appends_no_event(tmp_path: Path) -> None:
    # Append-only parity with add_note/add_edge: no state change → no event line.
    path = tmp_path / "index.jsonl"
    repo = JsonlNoteRepository(path)
    repo.add_note(_note("a1", "First"), (1.0, 0.0))  # creation status NEXT
    before = path.read_text(encoding="utf-8")
    repo.set_status("a1", NoteStatus.NEXT)  # equals derived status → no-op
    assert path.read_text(encoding="utf-8") == before

    repo.set_status("a1", NoteStatus.DONE)
    repo.set_status("a1", NoteStatus.DONE)  # idempotent: the second changes nothing
    assert path.read_text(encoding="utf-8").count('"kind": "status"') == 1


# -- PR-C: edit events + timestamps + history persistence ---------------------------------------


def test_edit_event_persists_and_rehydrates(tmp_path: Path) -> None:
    path = tmp_path / "index.jsonl"
    repo = JsonlNoteRepository(path)
    repo.add_note(_note("a1", "First"), (1.0, 0.0))
    repo.record_edit(
        "a1", NoteEdit(title="First (renamed)", due="2026-09-01"), at="2026-06-17T00:00:00Z"
    )

    reopened = JsonlNoteRepository(path)
    current = reopened.current_note("a1")
    assert current is not None
    assert current.title == "First (renamed)" and current.due == "2026-09-01"
    stored = reopened.get_note("a1")
    assert stored is not None and stored.title == "First"  # stored note untouched (lossless)
    history = reopened.history_of("a1")
    assert history[-1].kind == "edit" and history[-1].at == "2026-06-17T00:00:00Z"


def test_edit_persists_all_field_kinds(tmp_path: Path) -> None:
    # body and tags edits must round-trip through JSON too (not just title/due).
    path = tmp_path / "index.jsonl"
    repo = JsonlNoteRepository(path)
    repo.add_note(_note("a1", "First"), (1.0, 0.0))
    repo.record_edit("a1", NoteEdit(body="rewritten body", tags=("x", "y")))

    current = JsonlNoteRepository(path).current_note("a1")
    assert current is not None
    assert current.body == "rewritten body" and current.tags == ("x", "y")


def test_resource_event_persists_and_rehydrates(tmp_path: Path) -> None:
    # PR-E: an attached resource is an event; derived resources survive a reopen.
    path = tmp_path / "index.jsonl"
    repo = JsonlNoteRepository(path)
    repo.add_note(_note("a1", "First"), (1.0, 0.0))
    repo.add_resource("a1", Resource(ResourceKind.FILE, "/docs/a1.pdf"), at="2026-06-17T00:00:00Z")
    repo.add_resource("a1", Resource(ResourceKind.FILE, "/docs/a1.pdf"))  # duplicate → no event

    reopened = JsonlNoteRepository(path)
    assert reopened.resources_of("a1") == (Resource(ResourceKind.FILE, "/docs/a1.pdf"),)
    current = reopened.current_note("a1")
    assert current is not None and current.resources == (
        Resource(ResourceKind.FILE, "/docs/a1.pdf"),
    )
    assert path.read_text(encoding="utf-8").count('"kind": "resource"') == 1  # idempotent on disk


def test_status_event_timestamp_rehydrates(tmp_path: Path) -> None:
    path = tmp_path / "index.jsonl"
    repo = JsonlNoteRepository(path)
    repo.add_note(_note("a1", "First"), (1.0, 0.0))
    repo.set_status("a1", NoteStatus.DONE, at="2026-06-17T09:00:00Z")

    reopened = JsonlNoteRepository(path)
    assert reopened.status_of("a1") is NoteStatus.DONE
    (event,) = [e for e in reopened.history_of("a1") if e.kind == "status"]
    assert event.at == "2026-06-17T09:00:00Z"


def test_unknown_record_kind_is_skipped_not_crashed(tmp_path: Path) -> None:
    # Forward-incompatible / corrupt lines must be skipped (logged), never crash rehydration.
    path = tmp_path / "index.jsonl"
    repo = JsonlNoteRepository(path)
    repo.add_note(_note("a1", "First"), (1.0, 0.0))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "from-the-future", "payload": 1}\n')

    reopened = JsonlNoteRepository(path)  # must not raise
    assert reopened.get_note("a1") is not None  # the good record still loaded


def test_noop_or_unknown_edit_appends_no_line(tmp_path: Path) -> None:
    path = tmp_path / "index.jsonl"
    repo = JsonlNoteRepository(path)
    repo.add_note(_note("a1", "First"), (1.0, 0.0))
    before = path.read_text(encoding="utf-8")
    repo.record_edit("a1", NoteEdit(title="First"))  # same as current → no-op
    repo.record_edit("ghost", NoteEdit(title="x"))  # unknown note → orphan-guarded
    assert path.read_text(encoding="utf-8") == before
