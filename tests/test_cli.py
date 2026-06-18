"""Tests for the CLI / organize_text end-to-end run (incl. --llm / --embeddings flags)."""

from __future__ import annotations

import builtins
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from grandplan.cli import main, organize_text
from grandplan.core.models import Note, NoteType, Original, ProposedNote, Source


def _block_import(monkeypatch: pytest.MonkeyPatch, module: str) -> None:
    """Force `import <module>` to fail, so the missing-dependency path is exercised
    deterministically whether or not the optional extra is installed in this env."""
    real_import: Callable[..., object] = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == module or name.startswith(f"{module}."):
            raise ImportError(f"No module named {module!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


_SOURCE = Source(app="cli", title="notes.txt")
_CREATED = "2026-06-15T00:00:00Z"

_MESSY = """Project kickoff
schedule the first planning meeting

Buy groceries: milk, eggs, bread

Project kickoff
schedule the first planning meeting

Research neural networks and machine learning for the project
"""


def test_attach_command_matches_a_note_and_records_a_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PR-E: `grandplan attach <ref> -o <vault>` attaches the artifact to the note it fulfils.
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))  # keep the index out of real $HOME
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.embed import HashingEmbedder
    from grandplan.core.note_store import JsonlNoteRepository
    from grandplan.core.resources import ResourceKind

    vault = tmp_path / "vault"
    index = migrate_legacy_index(vault) / "index.jsonl"
    seed = JsonlNoteRepository(index)
    note = Note(
        id="r1", original_id="o", title="build the resume website", body="b", type=NoteType.TASK
    )
    seed.add_note(note, HashingEmbedder().embed(note.title))

    code = main(["attach", "/Users/me/resume-final.pdf", "-o", str(vault)])

    assert code == 0
    reopened = JsonlNoteRepository(index)
    resources = reopened.resources_of("r1")
    assert len(resources) == 1 and resources[0].kind is ResourceKind.FILE


def test_attach_command_reports_no_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    assert main(["attach", "/tmp/x.pdf", "-o", str(tmp_path / "empty-vault")]) == 1  # no notes


def test_rerender_command_resolves_links_and_writes_graph_colours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    from grandplan.core.embed import HashingEmbedder
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository

    vault = tmp_path / "vault"
    repo = JsonlNoteRepository(migrate_legacy_index(vault) / "index.jsonl")
    a = Note(id="a1", original_id="oa", title="alpha note", body="b", type=NoteType.TASK)
    repo.add_note(a, HashingEmbedder().embed("alpha"))

    assert main(["rerender", "-o", str(vault)]) == 0
    assert (vault / ".obsidian" / "graph.json").exists()  # graph colours written
    assert main(["rerender", "-o", str(tmp_path / "no-such-vault")]) == 1  # no index → error


def test_organize_text_writes_vault_graph_and_plan(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    summary = organize_text(_MESSY, source=_SOURCE, created=_CREATED, vault_dir=vault)

    assert summary.notes == 3  # 4 paragraphs, one exact duplicate skipped
    assert summary.skipped_duplicates == 1
    assert summary.graph_path.exists()
    assert summary.plan_path.exists()

    md_files = list(vault.glob("*.md"))
    assert any(p.name == "Plan.md" for p in md_files)
    note_files = [p for p in md_files if p.name != "Plan.md"]
    assert len(note_files) == summary.notes


def test_graph_json_matches_committed_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    summary = organize_text(_MESSY, source=_SOURCE, created=_CREATED, vault_dir=vault)
    data = json.loads(summary.graph_path.read_text(encoding="utf-8"))
    assert len(data["nodes"]) == summary.notes


def test_main_organize_file_returns_zero_and_writes_outputs(tmp_path: Path) -> None:
    src = tmp_path / "notes.txt"
    src.write_text(_MESSY, encoding="utf-8")
    vault = tmp_path / "vault"

    code = main(["organize", str(src), "-o", str(vault)])

    assert code == 0
    assert (vault / "Plan.md").exists()
    assert (vault / "graph.json").exists()


class _StubOrganizer:
    def organize(self, original: Original) -> ProposedNote:
        return ProposedNote(
            original_id=original.id,
            title="STUB TITLE",
            body=original.text.strip(),
            type=NoteType.TASK,
            tags=("stub",),
        )


def test_organize_text_uses_injected_organizer(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    organize_text(
        "one note here",
        source=_SOURCE,
        created=_CREATED,
        vault_dir=vault,
        organizer=_StubOrganizer(),
    )
    note = next(p for p in vault.glob("*.md") if p.name != "Plan.md")
    assert "# STUB TITLE" in note.read_text(encoding="utf-8")


def test_main_llm_flag_falls_back_without_ollama(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "n.txt"
    src.write_text("Buy milk and eggs", encoding="utf-8")
    vault = tmp_path / "vault"

    # No Ollama -> OllamaOrganizer catches the failure and falls back to the baseline.
    _block_import(monkeypatch, "ollama")
    code = main(["organize", str(src), "-o", str(vault), "--llm"])
    assert code == 0
    assert (vault / "Plan.md").exists()


def test_main_embeddings_flag_reports_missing_dependency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "n.txt"
    src.write_text("Buy milk and eggs", encoding="utf-8")
    vault = tmp_path / "vault"

    _block_import(monkeypatch, "sentence_transformers")
    code = main(["organize", str(src), "-o", str(vault), "--embeddings"])
    assert code == 1
    assert "sentence-transformers" in capsys.readouterr().err


def test_main_gui_without_pyside_reports_missing_dependency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _block_import(monkeypatch, "PySide6")
    code = main(["gui", "-o", str(tmp_path / "vault")])
    assert code == 1
    assert "PySide6" in capsys.readouterr().err


def test_main_gui_embeddings_without_dep_fails_fast(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # --embeddings without sentence-transformers must fail fast at startup with install
    # guidance, never launch Qt and crash on the first capture (the Windows traceback).
    import importlib.util as ilu

    real_find_spec = ilu.find_spec
    monkeypatch.setattr(
        ilu,
        "find_spec",
        lambda name, *a, **k: None if name == "sentence_transformers" else real_find_spec(name),
    )
    code = main(["gui", "-o", str(tmp_path / "vault"), "--embeddings"])
    assert code == 1
    assert "sentence-transformers" in capsys.readouterr().err
