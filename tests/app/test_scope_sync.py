"""Tests for resolving the graph filter into a chat scope (SPEC-SCOPE §5).

End-to-end over the real pieces (read graph.json → parse → select), plus the human-readable summary
that the REPL prints and the GUI chip shows — including the three "falls back to the whole vault"
cases, which must be told apart, not collapsed into one message.
"""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.app.scope_sync import resolve_graph_scope
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Note, NoteType
from grandplan.core.repository import InMemoryNoteRepository


def _repo() -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    embedder = HashingEmbedder()
    for note_id, title, tags in (
        ("a", "Career growth", ("career",)),
        ("b", "Education roadmap", ("career", "education")),
        ("c", "Grocery list", ("home",)),
    ):
        note = Note(
            id=note_id,
            original_id=f"o-{note_id}",
            title=title,
            body=title,
            type=NoteType.IDEA,
            tags=tags,
        )
        repo.add_note(note, embedder.embed(note.body))
    return repo


def _write_filter(vault_dir: Path, search: str) -> None:
    config = vault_dir / ".obsidian" / "graph.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"search": search}), encoding="utf-8")


def test_filter_scopes_to_the_matching_notes(tmp_path: Path) -> None:
    _write_filter(tmp_path, "#career")
    result = resolve_graph_scope(tmp_path, _repo())
    assert result.ids == frozenset({"a", "b"})
    assert result.narrowed and result.count == 2
    assert "scoped to 2 of 3 notes" in result.summary()
    assert "#career" in result.summary()


def test_no_graph_config_is_whole_vault(tmp_path: Path) -> None:
    result = resolve_graph_scope(tmp_path, _repo())
    assert result.ids == frozenset()
    assert not result.narrowed
    assert "no graph filter set" in result.summary()


def test_all_negation_filter_is_whole_vault(tmp_path: Path) -> None:
    _write_filter(tmp_path, '-path:"Plan.md" -path:"graph.json"')
    result = resolve_graph_scope(tmp_path, _repo())
    assert result.ids == frozenset()
    assert not result.narrowed
    assert "doesn't narrow anything" in result.summary()


def test_zero_match_filter_is_distinct_from_no_filter(tmp_path: Path) -> None:
    # A filter that DID try to narrow but hit nothing must say so — not "doesn't narrow anything".
    _write_filter(tmp_path, "#nonexistent")
    result = resolve_graph_scope(tmp_path, _repo())
    assert result.ids == frozenset()
    assert result.narrowed  # it tried
    assert "matched 0 notes" in result.summary()


def test_unsupported_operators_are_surfaced_in_the_summary(tmp_path: Path) -> None:
    _write_filter(tmp_path, "#career line:5")
    result = resolve_graph_scope(tmp_path, _repo())
    assert result.ids == frozenset({"a", "b"})  # supported part still scopes (fails open)
    assert "ignored line:5" in result.summary()
    assert "may be broader" in result.summary()
