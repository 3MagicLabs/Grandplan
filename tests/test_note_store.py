"""Tests for JsonlNoteRepository — the persistent, rehydrating note index.

The GUI keeps an index in memory; without persistence a restart would forget every prior note,
so new captures could never link to history (US-5). This store mirrors the JsonlOriginalStore
pattern: append-only, idempotent, and lossless across a reopen.
"""

from __future__ import annotations

from pathlib import Path

from grandplan.core.models import Edge, EdgeKind, Note, NoteStatus, NoteType
from grandplan.core.note_store import JsonlNoteRepository


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


def test_creates_missing_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "vault" / ".grandplan" / "index.jsonl"
    JsonlNoteRepository(path).add_note(_note("a1", "First"), (1.0, 0.0))
    assert path.exists()
