"""Tests for reading the Obsidian graph filter (SPEC-SCOPE §5).

Total and best-effort: it returns the `search` string when there is one and `None` for every kind of
absent/broken config, and never raises — a bad graph.json must not take chat down.
"""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.adapters.obsidian_graph import read_graph_filter


def _write_graph_json(vault_dir: Path, content: str) -> None:
    config = vault_dir / ".obsidian" / "graph.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(content, encoding="utf-8")


def test_reads_the_search_field(tmp_path: Path) -> None:
    _write_graph_json(tmp_path, json.dumps({"search": "#career education", "colorGroups": []}))
    assert read_graph_filter(tmp_path) == "#career education"


def test_missing_config_is_none(tmp_path: Path) -> None:
    assert read_graph_filter(tmp_path) is None


def test_invalid_json_is_none(tmp_path: Path) -> None:
    _write_graph_json(tmp_path, "{ not json")
    assert read_graph_filter(tmp_path) is None


def test_non_object_json_is_none(tmp_path: Path) -> None:
    _write_graph_json(tmp_path, json.dumps(["a", "list"]))
    assert read_graph_filter(tmp_path) is None


def test_non_string_search_is_none(tmp_path: Path) -> None:
    _write_graph_json(tmp_path, json.dumps({"search": 123}))
    assert read_graph_filter(tmp_path) is None


def test_missing_search_key_is_none(tmp_path: Path) -> None:
    _write_graph_json(tmp_path, json.dumps({"colorGroups": []}))
    assert read_graph_filter(tmp_path) is None


def test_blank_search_is_none(tmp_path: Path) -> None:
    _write_graph_json(tmp_path, json.dumps({"search": "   "}))
    assert read_graph_filter(tmp_path) is None
