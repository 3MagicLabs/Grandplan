"""Tests for cross-vault import — appending one vault's notes/captures into another (append-only)."""

from __future__ import annotations

from pathlib import Path

from grandplan.core.models import Edge, EdgeKind, Note, NoteType, Original, Source
from grandplan.core.note_store import JsonlNoteRepository
from grandplan.core.store import JsonlOriginalStore
from grandplan.core.vault_import import import_index_records, import_inbox_records


def _note(note_id: str, title: str, note_type: NoteType = NoteType.IDEA) -> Note:
    return Note(id=note_id, original_id=f"o-{note_id}", title=title, body="b", type=note_type)


def test_import_merges_source_notes_and_edges_into_destination(tmp_path: Path) -> None:
    src, dest = tmp_path / "src.jsonl", tmp_path / "dest.jsonl"
    source = JsonlNoteRepository(src)
    source.add_note(_note("n1", "Alpha"), (1.0,))
    source.add_note(_note("n2", "Beta", NoteType.TASK), (1.0,))
    source.add_edge(Edge("n1", "n2", EdgeKind.RELATES))
    dest_repo = JsonlNoteRepository(dest)
    dest_repo.add_note(_note("d1", "Existing"), (1.0,))

    imported = import_index_records(src, dest, skip_note_ids={"d1"})
    assert imported == {"n1", "n2"}  # note ids imported (to be protected on re-projection)

    merged = JsonlNoteRepository(dest)
    assert {note.id for note in merged.notes()} == {"d1", "n1", "n2"}
    beta = merged.get_note("n2")
    assert beta is not None and beta.title == "Beta"  # imported note carried its fields
    assert merged.get_note("d1") is not None  # the destination's own note is untouched
    edge = merged.edges()
    assert any(e.source_id == "n1" and e.target_id == "n2" for e in edge)  # edges came along


def test_import_skips_ids_the_destination_already_has_and_is_idempotent(tmp_path: Path) -> None:
    src, dest = tmp_path / "src.jsonl", tmp_path / "dest.jsonl"
    source = JsonlNoteRepository(src)
    source.add_note(_note("n1", "One"), (1.0,))
    source.add_note(_note("n2", "Two"), (1.0,))

    first = import_index_records(src, dest, skip_note_ids=set())
    assert first == {"n1", "n2"}
    after_first = {note.id for note in JsonlNoteRepository(dest).notes()}

    # Re-importing while skipping what's now present adds nothing and creates no duplicate lines.
    dest_ids = {note.id for note in JsonlNoteRepository(dest).notes()}
    second = import_index_records(src, dest, skip_note_ids=dest_ids)
    assert second == set()
    assert {note.id for note in JsonlNoteRepository(dest).notes()} == after_first == {"n1", "n2"}


def test_import_missing_source_index_is_a_noop(tmp_path: Path) -> None:
    assert import_index_records(tmp_path / "nope.jsonl", tmp_path / "dest.jsonl", set()) == set()


def test_import_inbox_appends_new_originals_only(tmp_path: Path) -> None:
    src, dest = tmp_path / "si.jsonl", tmp_path / "di.jsonl"
    source = JsonlOriginalStore(src)
    source.add(Original(id="o1", text="capture one", source=Source(app="x"), created="2026-01-01"))
    source.add(Original(id="o2", text="capture two", source=Source(app="x"), created="2026-01-01"))
    dest_store = JsonlOriginalStore(dest)
    dest_store.add(
        Original(id="o1", text="already here", source=Source(app="x"), created="2026-01-01")
    )

    count = import_inbox_records(src, dest, skip_ids={"o1"})
    assert count == 1  # only o2 is new

    merged = JsonlOriginalStore(dest)
    assert {original.id for original in merged.all()} == {"o1", "o2"}
    kept = merged.get("o1")
    assert kept is not None and kept.text == "already here"  # existing capture not overwritten
