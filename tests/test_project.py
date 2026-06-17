"""Tests for write_projections — graph.json + Plan.md regenerated from the repository."""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.core.models import Note, NoteType
from grandplan.core.project import write_projections
from grandplan.core.repository import InMemoryNoteRepository


def _repo() -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    repo.add_note(
        Note(id="t1", original_id="o1", title="Do the thing", body="b", type=NoteType.TASK),
        (1.0,),
    )
    return repo


def test_write_projections_writes_graph_and_plan(tmp_path: Path) -> None:
    graph_path, plan_path = write_projections(_repo(), tmp_path / "vault")
    assert graph_path.name == "graph.json"
    assert plan_path.name == "Plan.md"
    assert json.loads(graph_path.read_text(encoding="utf-8"))["nodes"][0]["id"] == "t1"
    plan = plan_path.read_text(encoding="utf-8")
    assert "# Plan" in plan
    assert "- [ ] Do the thing" in plan


def test_write_projections_creates_missing_vault_dir(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "vault"
    write_projections(_repo(), target)
    assert (target / "Plan.md").exists()
    assert (target / "graph.json").exists()
