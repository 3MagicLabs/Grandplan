"""Tests for write_projections — graph.json + Plan.md regenerated from the repository."""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.core.models import Note, NoteEdit, NoteStatus, NoteType, Original, Source
from grandplan.core.project import write_projections
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore


def _repo() -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    repo.add_note(
        Note(id="t1", original_id="o1", title="Do the thing", body="b", type=NoteType.TASK),
        (1.0,),
    )
    return repo


def _original(oid: str = "o1", text: str = "verbatim") -> Original:
    return Original(id=oid, text=text, source=Source(app="x"), created="2026-06-17T00:00:00Z")


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


# -- PR-C: note .md re-render from derived state ------------------------------------------------


def test_originals_re_render_notes_with_derived_status_edits_and_history(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    repo = _repo()
    originals = InMemoryOriginalStore()
    originals.add(_original())
    repo.set_status("t1", NoteStatus.DONE, at="2026-06-17T11:00:00Z")
    repo.record_edit("t1", NoteEdit(due="2026-09-01"), at="2026-06-17T12:00:00Z")

    write_projections(repo, vault, originals=originals)

    note_md = next(
        p for p in vault.glob("*.md") if p.name not in ("Plan.md", "Masterplan.md", "Timeline.md")
    ).read_text(encoding="utf-8")
    assert 'status: "done"' in note_md  # derived status now in the note file (PR-A/B deferred item)
    assert 'due: "2026-09-01"' in note_md  # edited field
    assert "## History" in note_md and "status → done" in note_md and "edit: due" in note_md


def test_without_originals_notes_are_not_re_rendered(tmp_path: Path) -> None:
    # Back-compatible: omitting `originals` keeps the lighter graph + Plan-only behaviour.
    vault = tmp_path / "vault"
    write_projections(_repo(), vault)  # no originals
    assert sorted(p.name for p in vault.glob("*.md")) == [
        "Masterplan.md",
        "Plan.md",
        "Timeline.md",
    ]  # no notes


def test_title_edit_re_render_leaves_no_orphan_file(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    repo = _repo()
    originals = InMemoryOriginalStore()
    originals.add(_original())

    write_projections(repo, vault, originals=originals)  # writes "do-the-thing.md"
    assert (vault / "do-the-thing.md").exists()
    repo.record_edit("t1", NoteEdit(title="Do the renamed thing"))
    write_projections(repo, vault, originals=originals)  # re-render under the new slug

    assert not (vault / "do-the-thing.md").exists()  # the stale old-title file was swept
    notes = sorted(
        p.name
        for p in vault.glob("*.md")
        if p.name not in ("Plan.md", "Masterplan.md", "Timeline.md")
    )
    assert len(notes) == 1  # exactly one note file — the old-title file was swept, not orphaned
    body = (vault / notes[0]).read_text(encoding="utf-8")
    assert "# Do the renamed thing" in body


def test_note_without_a_stored_original_is_skipped_not_rendered_lossy(tmp_path: Path) -> None:
    # Losslessness: we never render a note whose verbatim source is missing — skip it (logged).
    vault = tmp_path / "vault"
    repo = _repo()  # note t1 references original "o1"
    originals = InMemoryOriginalStore()  # ...which is absent here
    write_projections(repo, vault, originals=originals)
    assert sorted(p.name for p in vault.glob("*.md")) == [
        "Masterplan.md",
        "Plan.md",
        "Timeline.md",
    ]  # no notes


def test_graph_colours_fill_empty_groups_but_respect_user_groups(tmp_path: Path) -> None:
    from grandplan.core.project import write_obsidian_config

    vault = tmp_path / "vault"
    cfg = vault / ".obsidian" / "graph.json"
    cfg.parent.mkdir(parents=True)

    # An existing config with EMPTY colour groups (the real-world case) → we fill it, keep settings.
    cfg.write_text(json.dumps({"colorGroups": [], "scale": 0.7, "showOrphans": True}), "utf-8")
    write_obsidian_config(vault)
    data = json.loads(cfg.read_text("utf-8"))
    assert len(data["colorGroups"]) == 8 and data["scale"] == 0.7  # filled, other settings kept

    # A config where the user already chose colours → untouched.
    cfg.write_text(json.dumps({"colorGroups": [{"query": "tag:#mine", "color": {}}]}), "utf-8")
    write_obsidian_config(vault)
    assert json.loads(cfg.read_text("utf-8"))["colorGroups"] == [
        {"query": "tag:#mine", "color": {}}
    ]


def test_phantom_id_stub_files_are_swept(tmp_path: Path) -> None:
    from grandplan.core.project import remove_phantom_link_files

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "5d2da2de0e4dec45.md").write_text("", encoding="utf-8")  # empty Obsidian phantom stub
    (vault / "abc123def4567890.md").write_text("   \n", encoding="utf-8")  # whitespace-only stub
    (vault / "real-note.md").write_text("# Real\nkeep me", encoding="utf-8")  # real file → keep
    (vault / "0123456789abcdef.md").write_text(
        "I typed notes here", encoding="utf-8"
    )  # non-empty → keep

    assert remove_phantom_link_files(vault) == 2
    assert not (vault / "5d2da2de0e4dec45.md").exists()
    assert (vault / "real-note.md").exists() and (vault / "0123456789abcdef.md").exists()


def test_orphan_sweep_never_touches_foreign_files(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    foreign = vault / "my-notes.md"
    foreign.write_text("# Hand-written, no grandplan id\n", encoding="utf-8")
    repo = _repo()
    originals = InMemoryOriginalStore()
    originals.add(_original())

    write_projections(repo, vault, originals=originals)
    assert foreign.read_text(encoding="utf-8") == "# Hand-written, no grandplan id\n"
