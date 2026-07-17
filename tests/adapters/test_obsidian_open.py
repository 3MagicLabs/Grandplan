"""Tests for the Obsidian opener — graph-view workspace scaffold + the open URI (pure pieces)."""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.adapters.obsidian_open import (
    note_file,
    obsidian_open_uri,
    scaffold_graph_view,
)
from grandplan.core.models import Note, NoteType
from grandplan.core.vault import plan_filenames


def _note(note_id: str, title: str) -> Note:
    return Note(id=note_id, original_id=f"o-{note_id}", title=title, body="b", type=NoteType.IDEA)


def _render(vault: Path, notes: list[Note]) -> None:
    """Put a .md on disk for each note, at the stem the real projections would use."""
    vault.mkdir(parents=True, exist_ok=True)
    for note_id, stem in plan_filenames(notes).items():
        (vault / f"{stem}.md").write_text(f"# {note_id}", encoding="utf-8")


def test_scaffold_writes_workspace_opening_on_graph(tmp_path: Path) -> None:
    assert scaffold_graph_view(tmp_path) is True
    data = json.loads((tmp_path / ".obsidian" / "workspace.json").read_text(encoding="utf-8"))
    leaf = data["main"]["children"][0]
    assert leaf["state"]["type"] == "graph"
    assert data["active"] == leaf["id"]


def test_scaffold_is_non_destructive(tmp_path: Path) -> None:
    workspace = tmp_path / ".obsidian" / "workspace.json"
    workspace.parent.mkdir(parents=True)
    workspace.write_text('{"mine": true}', encoding="utf-8")
    assert scaffold_graph_view(tmp_path) is False  # existing layout untouched
    assert json.loads(workspace.read_text(encoding="utf-8")) == {"mine": True}


def test_open_uri_encodes_absolute_path(tmp_path: Path) -> None:
    uri = obsidian_open_uri(tmp_path)
    assert uri.startswith("obsidian://open?path=")
    assert "%2F" in uri or "%5C" in uri  # the absolute path is URL-encoded (no raw separators)
    assert " " not in uri  # spaces encoded


def test_open_uri_targets_a_note_file_inside_the_vault(tmp_path: Path) -> None:
    # `grandplan graph --open` hands Obsidian a note path, not a vault dir, so the user lands on the
    # note itself and can open its local-graph pane from there.
    note = tmp_path / "my note.md"
    note.write_text("# hi", encoding="utf-8")
    uri = obsidian_open_uri(note)
    assert uri.startswith("obsidian://open?path=")
    assert "my%20note.md" in uri  # the file (with its space encoded) is the target


def test_note_file_resolves_a_rendered_note(tmp_path: Path) -> None:
    notes = [_note("a", "First Idea"), _note("b", "Second Idea")]
    _render(tmp_path, notes)

    target = note_file("a", notes, tmp_path)

    assert target is not None
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "# a"


def test_note_file_agrees_with_the_wikilinks_inside_the_notes(tmp_path: Path) -> None:
    # The stem map is a pure function of the note SET, so two notes that slugify the same are
    # disambiguated identically here and in the [[links]] the projections write. If this drifted,
    # a clicked source would open the OTHER note of a colliding pair.
    notes = [_note("aaaaaa1", "Same Title"), _note("bbbbbb2", "Same Title")]
    _render(tmp_path, notes)

    first = note_file("aaaaaa1", notes, tmp_path)
    second = note_file("bbbbbb2", notes, tmp_path)

    assert first is not None and second is not None
    assert first != second  # the collision is disambiguated, not silently merged
    assert first.read_text(encoding="utf-8") == "# aaaaaa1"
    assert second.read_text(encoding="utf-8") == "# bbbbbb2"


def test_note_file_is_none_for_an_unknown_id(tmp_path: Path) -> None:
    assert note_file("nope", [_note("a", "First")], tmp_path) is None


def test_note_file_is_none_when_the_index_knows_it_but_no_file_exists(tmp_path: Path) -> None:
    # Stale projections: the honest answer is None so the caller can say "run rerender". Falling
    # back to the vault root would open SOMETHING and hide that the note was never written.
    tmp_path.mkdir(parents=True, exist_ok=True)
    assert note_file("a", [_note("a", "Never Rendered")], tmp_path) is None
