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


def test_regenerating_overwrites_its_own_generated_files(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_projections(_repo(), vault)
    graph_path, plan_path = write_projections(_repo(), vault)  # second pass
    assert graph_path.name == "graph.json"  # overwrites in place, no divert
    assert plan_path.name == "Plan.md"


def test_foreign_plan_is_never_clobbered(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    handwritten = vault / "Plan.md"
    handwritten.write_text("# My hand-written plan\n\nDo not touch.\n", encoding="utf-8")

    graph_path, plan_path = write_projections(_repo(), vault)

    assert plan_path.name == "Plan.grandplan.md"  # diverted
    assert handwritten.read_text(encoding="utf-8") == "# My hand-written plan\n\nDo not touch.\n"
    assert "# Plan" in plan_path.read_text(encoding="utf-8")  # ours still produced


def test_foreign_graph_json_is_never_clobbered(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    # A foreign graph export that *coincidentally* uses the {nodes,edges} shape (D3/networkx) must
    # still be preserved — recognition relies on the _grandplan sentinel, not the shape.
    foreign = vault / "graph.json"
    foreign.write_text('{"nodes": ["theirs"], "edges": []}', encoding="utf-8")

    graph_path, _ = write_projections(_repo(), vault)

    assert graph_path.name == "graph.grandplan.json"  # diverted, not clobbered
    assert json.loads(foreign.read_text(encoding="utf-8")) == {"nodes": ["theirs"], "edges": []}


def test_chain_of_foreign_files_is_never_clobbered(tmp_path: Path) -> None:
    # Both Plan.md and Plan.grandplan.md belong to the user → divert past both, lose nothing.
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Plan.md").write_text("mine 1", encoding="utf-8")
    (vault / "Plan.grandplan.md").write_text("mine 2", encoding="utf-8")

    _, plan_path = write_projections(_repo(), vault)

    assert plan_path.name == "Plan.grandplan.grandplan.md"
    assert (vault / "Plan.md").read_text(encoding="utf-8") == "mine 1"
    assert (vault / "Plan.grandplan.md").read_text(encoding="utf-8") == "mine 2"
