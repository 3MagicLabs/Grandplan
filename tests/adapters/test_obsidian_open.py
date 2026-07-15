"""Tests for the Obsidian opener — graph-view workspace scaffold + the open URI (pure pieces)."""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.adapters.obsidian_open import (
    obsidian_open_uri,
    scaffold_graph_view,
)


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
