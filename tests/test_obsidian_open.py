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
