"""Tests for the CLI / organize_text end-to-end run (incl. --llm / --embeddings flags)."""

from __future__ import annotations

import builtins
import json
import re
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


def test_regenerate_rebuilds_from_originals_and_backs_up_old_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # PR-F (RC4): `regenerate` re-organizes the vault from the lossless inbox originals; the old
    # index is backed up and the originals are never touched.
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    from grandplan.core.embed import HashingEmbedder
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository
    from grandplan.core.store import JsonlOriginalStore

    vault = tmp_path / "vault"
    index_root = migrate_legacy_index(vault)
    inbox = JsonlOriginalStore(index_root / "inbox.jsonl")
    original = Original.capture("buy milk and eggs for the week", Source(app="cli"), _CREATED)
    inbox.add(original)
    # A stale heuristic-era note in the index that regenerate should replace.
    stale = JsonlNoteRepository(index_root / "index.jsonl")
    stale.add_note(
        Note(id="old", original_id=original.id, title="x", body="x", type=NoteType.IDEA),
        HashingEmbedder().embed("x"),
    )

    code = main(["regenerate", "-o", str(vault), "--no-llm"])

    assert code == 0
    assert (index_root / "index.jsonl.bak").exists()  # old index preserved
    assert (vault / "Plan.md").exists()
    assert "regenerated" in capsys.readouterr().out
    rebuilt = JsonlNoteRepository(index_root / "index.jsonl")
    assert any(n.title.startswith("buy milk") for n in rebuilt.notes())
    # The lossless originals are never mutated by a rebuild.
    assert JsonlOriginalStore(index_root / "inbox.jsonl").get(original.id) == original


def test_regenerate_fails_loud_without_ollama_and_leaves_index_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Atomic safety: when the required model is unreachable, regenerate must ABORT without touching
    # the existing index (no .bak, no partial rebuild, temp cleaned).
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    from grandplan.core.embed import HashingEmbedder
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository
    from grandplan.core.store import JsonlOriginalStore

    vault = tmp_path / "vault"
    index_root = migrate_legacy_index(vault)
    original = Original.capture("buy milk and eggs", Source(app="cli"), _CREATED)
    JsonlOriginalStore(index_root / "inbox.jsonl").add(original)
    repo = JsonlNoteRepository(index_root / "index.jsonl")
    repo.add_note(
        Note(id="keep", original_id=original.id, title="keep me", body="b", type=NoteType.IDEA),
        HashingEmbedder().embed("keep"),
    )
    before = (index_root / "index.jsonl").read_text(encoding="utf-8")

    _block_import(monkeypatch, "ollama")
    code = main(["regenerate", "-o", str(vault)])  # default LLM, blocked → fail loud

    assert code == 1
    assert "aborted" in capsys.readouterr().err
    assert not (index_root / "index.jsonl.bak").exists()  # never backed up (nothing happened)
    assert not (index_root / "index.regen.jsonl").exists()  # temp cleaned up
    assert (index_root / "index.jsonl").read_text(encoding="utf-8") == before  # untouched


def test_regenerate_with_no_originals_reports_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    assert main(["regenerate", "-o", str(tmp_path / "empty"), "--no-llm"]) == 1


def test_regenerate_keep_history_replays_status_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A from-scratch rebuild resets event history; --keep-history replays it onto surviving notes.
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.models import NoteStatus as _NS
    from grandplan.core.note_store import JsonlNoteRepository
    from grandplan.core.store import JsonlOriginalStore

    vault = tmp_path / "vault"
    index_root = migrate_legacy_index(vault)
    index = index_root / "index.jsonl"
    # Seed a lossless original, then build the index from it (deterministic --no-llm → stable ids).
    JsonlOriginalStore(index_root / "inbox.jsonl").add(
        Original.capture("buy milk and eggs for the week", Source(app="cli"), _CREATED)
    )
    assert main(["regenerate", "-o", str(vault), "--no-llm"]) == 0
    note_id = JsonlNoteRepository(index).notes()[0].id

    # without --keep-history the rebuilt note loses the status (back to its creation status)
    JsonlNoteRepository(index).set_status(note_id, _NS.DONE, at=_CREATED)
    assert main(["regenerate", "-o", str(vault), "--no-llm"]) == 0
    assert JsonlNoteRepository(index).status_of(note_id) is not _NS.DONE  # history reset

    # re-apply the status, then regenerate WITH --keep-history → it survives the rebuild
    JsonlNoteRepository(index).set_status(note_id, _NS.DONE, at=_CREATED)
    assert main(["regenerate", "-o", str(vault), "--no-llm", "--keep-history"]) == 0
    assert JsonlNoteRepository(index).status_of(note_id) is _NS.DONE


def test_organize_persists_to_index_for_doctor_and_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The gap fix: `organize` writes the persistent index (not just the Obsidian vault), so the
    # index-reading commands (doctor/report/export/...) see what it produced — no GUI/regenerate needed.
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository
    from grandplan.core.store import JsonlOriginalStore

    src = tmp_path / "n.txt"
    src.write_text("finish the quickstart doc\n\nbuy milk and eggs", encoding="utf-8")
    vault = tmp_path / "vault"
    assert main(["organize", str(src), "-o", str(vault), "--no-llm"]) == 0

    index_root = migrate_legacy_index(vault)
    assert JsonlNoteRepository(index_root / "index.jsonl").notes()  # index populated
    assert JsonlOriginalStore(index_root / "inbox.jsonl").all()  # originals persisted (regen works)
    # the index-reading commands now succeed (previously: "no index found")
    assert main(["doctor", "-o", str(vault)]) == 0
    assert main(["export", "-o", str(vault), "--format", "tasks"]) == 0

    # re-organizing the same input is idempotent (append-only stores): all skipped as duplicates
    assert main(["organize", str(src), "-o", str(vault), "--no-llm"]) == 0
    assert len(JsonlNoteRepository(index_root / "index.jsonl").notes()) == 2


def test_replay_history_covers_all_event_kinds(tmp_path: Path) -> None:
    # Unit-test the replay helper across status/edit/resource/deleted + a dropped (unknown id) event.
    from grandplan.cli import _replay_history
    from grandplan.core.embed import HashingEmbedder
    from grandplan.core.models import NoteEdit, NoteEvent
    from grandplan.core.models import NoteStatus as _NS
    from grandplan.core.note_store import JsonlNoteRepository
    from grandplan.core.resources import Resource, ResourceKind

    repo = JsonlNoteRepository(tmp_path / "index.jsonl")
    repo.add_note(
        Note(id="n", original_id="o", title="t", body="b", type=NoteType.TASK),
        HashingEmbedder().embed("t"),
    )
    events = (
        NoteEvent("n", "status", at=_CREATED, status=_NS.ACTIVE),
        NoteEvent("n", "edit", at=_CREATED, edit=NoteEdit(title="renamed")),
        NoteEvent(
            "n", "resource", at=_CREATED, resource=Resource(ResourceKind.LINK, "https://x.io")
        ),
        NoteEvent("ghost", "status", at=_CREATED, status=_NS.DONE),  # unknown id → dropped
        NoteEvent("n", "deleted", at=_CREATED),
    )
    preserved, dropped = _replay_history(events, repo)
    assert (preserved, dropped) == (4, 1)


def _seed_vault(tmp_path: Path) -> "tuple[Path, Path]":
    """Organize a couple of notes into a vault; return (vault_dir, index_root)."""
    from grandplan.core.index_location import index_dir

    vault = tmp_path / "vault"
    src = tmp_path / "n.txt"
    src.write_text("buy milk\n\ncall Sarah Chen", encoding="utf-8")
    assert main(["organize", str(src), "-o", str(vault), "--no-llm"]) == 0
    return vault, index_dir(vault)


def test_reset_yes_deletes_vault_and_index(tmp_path: Path) -> None:
    vault, index_root = _seed_vault(tmp_path)
    assert vault.exists() and (index_root / "index.jsonl").exists()
    assert main(["reset", "-o", str(vault), "--yes"]) == 0
    assert not vault.exists()
    assert not index_root.exists()


def test_reset_keep_originals_preserves_inbox_for_regenerate(tmp_path: Path) -> None:
    vault, index_root = _seed_vault(tmp_path)
    assert main(["reset", "-o", str(vault), "--yes", "--keep-originals"]) == 0
    assert not vault.exists()
    assert not (index_root / "index.jsonl").exists()  # derived notes gone
    assert (index_root / "inbox.jsonl").exists()  # captures kept
    # regenerate rebuilds from the kept originals
    assert main(["regenerate", "-o", str(vault), "--no-llm"]) == 0
    assert (vault / "Plan.md").exists()


def test_reset_aborts_on_no(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault, _ = _seed_vault(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    assert main(["reset", "-o", str(vault)]) == 1  # no --yes → prompt → "n"
    assert vault.exists()  # nothing deleted


def test_reset_proceeds_on_yes_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault, _ = _seed_vault(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    assert main(["reset", "-o", str(vault)]) == 0
    assert not vault.exists()


def test_reset_refuses_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    assert main(["reset", "-o", str(fake_home), "--yes"]) == 1
    assert "refusing" in capsys.readouterr().err
    assert fake_home.exists()  # untouched


def test_reset_nothing_to_reset(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["reset", "-o", str(tmp_path / "never-existed"), "--yes"]) == 0
    assert "nothing to reset" in capsys.readouterr().out


def test_is_dangerous_delete_target_flags_root_and_home(tmp_path: Path) -> None:
    from grandplan.cli import _is_dangerous_delete_target

    assert _is_dangerous_delete_target(Path(tmp_path.anchor)) is True  # filesystem root
    assert _is_dangerous_delete_target(Path.home()) is True
    assert _is_dangerous_delete_target(tmp_path / "some" / "vault") is False


def test_doctor_reports_existing_vault_and_errors_without_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    from grandplan.core.embed import HashingEmbedder
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository
    from grandplan.core.store import JsonlOriginalStore

    vault = tmp_path / "vault"
    index_root = migrate_legacy_index(vault)
    original = Original.capture("buy milk", Source(app="cli"), _CREATED)
    JsonlOriginalStore(index_root / "inbox.jsonl").add(original)
    repo = JsonlNoteRepository(index_root / "index.jsonl")
    repo.add_note(
        Note(
            id="a", original_id=original.id, title="buy milk", body="buy milk", type=NoteType.IDEA
        ),
        HashingEmbedder().embed("buy milk"),
    )

    assert main(["doctor", "-o", str(vault)]) == 0
    out = capsys.readouterr().out
    assert "grandplan report" in out
    assert "no structural edges" in out  # the honest pre-PR-G diagnosis
    assert main(["doctor", "-o", str(tmp_path / "no-such-vault")]) == 1


def test_report_command_writes_deliverable_and_errors_without_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    from grandplan.core.embed import HashingEmbedder
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository
    from grandplan.core.store import JsonlOriginalStore

    vault = tmp_path / "vault"
    index_root = migrate_legacy_index(vault)
    original = Original.capture("write the launch post", Source(app="cli"), _CREATED)
    JsonlOriginalStore(index_root / "inbox.jsonl").add(original)
    repo = JsonlNoteRepository(index_root / "index.jsonl")
    repo.add_note(
        Note(
            id="a",
            original_id=original.id,
            title="Write the launch post",
            body="do it",
            type=NoteType.TASK,
        ),
        HashingEmbedder().embed("write the launch post"),
    )

    assert main(["report", "-o", str(vault), "--title", "Weekly status"]) == 0
    report_path = vault / "report.md"
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert text.startswith("# Weekly status")
    assert "Write the launch post" in text

    # stdout mode
    assert main(["report", "-o", str(vault), "--out", "-"]) == 0
    assert "# grandplan report" in capsys.readouterr().out

    assert main(["report", "-o", str(tmp_path / "no-such-vault")]) == 1


def test_export_command_writes_tasks_and_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    from grandplan.core.embed import HashingEmbedder
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository
    from grandplan.core.store import JsonlOriginalStore

    vault = tmp_path / "vault"
    index_root = migrate_legacy_index(vault)
    original = Original.capture("write the launch post", Source(app="cli"), _CREATED)
    JsonlOriginalStore(index_root / "inbox.jsonl").add(original)
    repo = JsonlNoteRepository(index_root / "index.jsonl")
    repo.add_note(
        Note(
            id="a",
            original_id=original.id,
            title="Write the launch post",
            body="do it",
            type=NoteType.TASK,
            due="2026-07-01",
        ),
        HashingEmbedder().embed("write the launch post"),
    )

    assert main(["export", "-o", str(vault), "--format", "tasks"]) == 0
    tasks = (vault / "tasks.md").read_text(encoding="utf-8")
    assert "- [ ] Write the launch post 📅 2026-07-01" in tasks

    assert main(["export", "-o", str(vault), "--format", "csv", "--out", "-"]) == 0
    assert "id,title,type,status,horizon,due,tags" in capsys.readouterr().out

    assert main(["export", "-o", str(vault), "--format", "todoist", "--out", "-"]) == 0
    todoist_out = capsys.readouterr().out
    assert "TYPE,CONTENT,DESCRIPTION,PRIORITY" in todoist_out
    assert "task,Write the launch post" in todoist_out

    assert main(["export", "-o", str(tmp_path / "no-such-vault")]) == 1


def test_directive_add_and_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    content = tmp_path / "post.txt"
    content.write_text("check out Sarah Chen at Acme Robotics", encoding="utf-8")

    code = main(
        [
            "directive",
            "add",
            "-o",
            str(vault),
            "--content",
            str(content),
            "--playbook",
            "profile-and-connect",
        ]
    )
    assert code == 0
    assert "queued directive" in capsys.readouterr().out

    assert main(["directive", "list", "-o", str(vault)]) == 0
    out = capsys.readouterr().out
    assert "profile-and-connect" in out
    assert "Sarah Chen" in out


def test_directive_add_unknown_playbook_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    content = tmp_path / "c.txt"
    content.write_text("x", encoding="utf-8")
    code = main(
        [
            "directive",
            "add",
            "-o",
            str(tmp_path / "v"),
            "--content",
            str(content),
            "--playbook",
            "nope",
        ]
    )
    assert code == 1


def test_up_dry_run_sets_up_and_prints_banner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "vault"
    code = main(["up", "-o", str(vault), "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "grandplan is up" in out
    assert "POST http://127.0.0.1:8765/directive" in out
    assert "mcp -o" in out and "--write --directives" in out
    assert (vault / "_inbox").is_dir()  # default watch folder created


def test_tilde_in_vault_path_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # `-o ~/MyVault` must expand to the home dir, not create a literal "~" folder in the CWD.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    # Path.expanduser() reads HOME (POSIX) / USERPROFILE (Windows); set both for portability.
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.chdir(tmp_path)

    assert main(["up", "-o", "~/MyVault", "--init", "--dry-run"]) == 0
    assert (fake_home / "MyVault" / "graph.json").exists()  # created under home
    assert not (tmp_path / "~").exists()  # no literal tilde folder


class _FakeCapturer:
    """A Capturer stand-in: returns a fixed selection (or None for 'nothing selected')."""

    def __init__(self, text: str | None) -> None:
        self._text = text

    def capture(self) -> str | None:
        return self._text


def test_capture_to_vault_organizes_the_selection(tmp_path: Path) -> None:
    from grandplan.cli import _capture_to_vault
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository

    vault = tmp_path / "vault"
    index_root = migrate_legacy_index(vault)
    captured = _capture_to_vault(
        _FakeCapturer("call Sarah Chen about the launch"),
        vault_dir=vault,
        index_root=index_root,
        created=_CREATED,
    )
    assert captured == "call Sarah Chen about the launch"
    notes = JsonlNoteRepository(index_root / "index.jsonl").notes()
    assert any("Sarah Chen" in n.title or "Sarah Chen" in n.body for n in notes)  # captured note
    assert any(n.type.value == "entity" for n in notes)  # entity auto-extracted


def test_capture_to_vault_ignores_empty_selection(tmp_path: Path) -> None:
    from grandplan.cli import _capture_to_vault
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository

    vault = tmp_path / "vault"
    index_root = migrate_legacy_index(vault)
    for nothing in (None, "   "):
        assert (
            _capture_to_vault(
                _FakeCapturer(nothing), vault_dir=vault, index_root=index_root, created=_CREATED
            )
            is None
        )
    assert JsonlNoteRepository(index_root / "index.jsonl").notes() == ()  # nothing written


def test_capture_to_vault_uses_the_injected_organizer(tmp_path: Path) -> None:
    # Proves the AI components flow through: a stub organizer (stand-in for the LLM) is used.
    from grandplan.cli import _capture_to_vault
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository

    vault = tmp_path / "vault"
    index_root = migrate_legacy_index(vault)
    _capture_to_vault(
        _FakeCapturer("some selected text"),
        vault_dir=vault,
        index_root=index_root,
        created=_CREATED,
        organizer=_StubOrganizer(),  # the slot the OllamaOrganizer fills under --llm
    )
    notes = JsonlNoteRepository(index_root / "index.jsonl").notes()
    assert any(n.title == "STUB TITLE" for n in notes)


def _force_specs_present(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Make importlib.util.find_spec report the given module names as installed (hermetic)."""
    import importlib.machinery
    import importlib.util

    real = importlib.util.find_spec
    present = set(names)
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: (
            importlib.machinery.ModuleSpec(name, loader=None) if name in present else real(name)
        ),
    )


def test_up_hotkey_shows_ai_enhanced_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Default: hotkey captures are AI-enhanced via the local model (graceful offline fallback).
    _force_specs_present(monkeypatch, "pynput", "ollama")
    code = main(["up", "-o", str(tmp_path / "v"), "--hotkey", "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "global hotkey: ctrl+shift+g" in out
    assert "AI-enhanced (gemma4:e4b)" in out


def test_up_hotkey_no_llm_shows_offline_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _force_specs_present(monkeypatch, "pynput")
    code = main(["up", "-o", str(tmp_path / "v"), "--hotkey", "--no-llm", "--dry-run"])
    assert code == 0
    assert "offline baseline" in capsys.readouterr().out


def test_up_hotkey_warns_when_ollama_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # pynput present, ollama absent → still starts (offline fallback), but warns the AI won't run.
    import importlib.machinery
    import importlib.util

    real = importlib.util.find_spec

    def fake_find_spec(name: str) -> object:
        if name == "pynput":
            return importlib.machinery.ModuleSpec("pynput", loader=None)
        if name == "ollama":
            return None  # force absent
        return real(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    code = main(["up", "-o", str(tmp_path / "v"), "--hotkey", "--dry-run"])
    assert code == 0
    assert "Ollama" in capsys.readouterr().err


def test_up_hotkey_missing_dependency_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name: None if name == "pynput" else real(name)
    )
    code = main(["up", "-o", str(tmp_path / "v"), "--hotkey", "--dry-run"])
    assert code == 1
    assert "windows" in capsys.readouterr().err  # points at the [windows] extra


def test_up_init_scaffolds_a_fresh_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "NewVault"
    code = main(["up", "-o", str(vault), "--init", "--dry-run"])
    assert code == 0
    assert "initialized vault" in capsys.readouterr().out
    assert (vault / "graph.json").exists()  # projections written
    assert (vault / ".obsidian" / "graph.json").exists()  # graph colours
    assert (vault / ".obsidian" / "workspace.json").exists()  # opens on the graph


def test_up_open_launches_obsidian(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(
        "grandplan.adapters.obsidian_open.open_in_obsidian",
        lambda vault_dir: opened.append(vault_dir) or True,
    )
    vault = tmp_path / "v"
    code = main(["up", "-o", str(vault), "--init", "--open", "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "opening graph view: obsidian://open?path=" in out
    assert opened == [vault]  # the launcher was invoked with our vault


def test_up_custom_folder_in_banner(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    drop = tmp_path / "drop"
    code = main(["up", "-o", str(tmp_path / "v"), "--folder", str(drop), "--dry-run"])
    assert code == 0
    assert str(drop) in capsys.readouterr().out
    assert drop.is_dir()


def test_up_refuses_routable_host_without_token(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["up", "-o", str(tmp_path / "v"), "--host", "0.0.0.0", "--dry-run"])  # noqa: S104
    assert code == 1
    assert "token" in capsys.readouterr().err


def test_up_rejects_unknown_playbook(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["up", "-o", str(tmp_path / "v"), "--playbook", "nope", "--dry-run"])
    assert code == 1
    assert "unknown playbook" in capsys.readouterr().err


def test_watch_once_enqueues_directives_from_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    from grandplan.core.directive import JsonlDirectiveStore
    from grandplan.core.index_location import migrate_legacy_index

    inbox = tmp_path / "drop"
    inbox.mkdir()
    (inbox / "idea.txt").write_text("research offline STT models", encoding="utf-8")
    vault = tmp_path / "vault"

    code = main(["watch", "-o", str(vault), "--folder", str(inbox), "--once"])
    assert code == 0
    assert "queued 1 directive" in capsys.readouterr().out
    store = JsonlDirectiveStore(migrate_legacy_index(vault) / "directives.jsonl")
    assert len(store.pending()) == 1


def test_watch_errors_on_missing_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    code = main(["watch", "-o", str(tmp_path / "v"), "--folder", str(tmp_path / "nope"), "--once"])
    assert code == 1
    assert "not a folder" in capsys.readouterr().err


def test_serve_refuses_routable_host_without_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    code = main(["serve", "-o", str(tmp_path / "v"), "--host", "0.0.0.0"])  # noqa: S104 - test only
    assert code == 1
    assert "token" in capsys.readouterr().err


def test_calendar_command_exports_ics_for_dated_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Calendar connector (offline): dated notes → a subscribe-able .ics file in the vault.
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    from grandplan.core.embed import HashingEmbedder
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository

    vault = tmp_path / "vault"
    repo = JsonlNoteRepository(migrate_legacy_index(vault) / "index.jsonl")
    repo.add_note(
        Note(
            id="a",
            original_id="o",
            title="file taxes",
            body="b",
            type=NoteType.TASK,
            due="2026-07-01",
        ),
        HashingEmbedder().embed("file taxes"),
    )

    assert main(["calendar", "-o", str(vault)]) == 0
    ics = (vault / "grandplan.ics").read_text(encoding="utf-8")
    assert "BEGIN:VEVENT" in ics and "DTSTART;VALUE=DATE:20260701" in ics
    assert "wrote 1 event" in capsys.readouterr().out
    assert main(["calendar", "-o", str(tmp_path / "no-such-vault")]) == 1  # no index → error


def test_mcp_command_reports_missing_dependency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # `grandplan mcp` needs the optional `mcp` extra; without it, a clear install error (not a crash).
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    from grandplan.core.embed import HashingEmbedder
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository

    vault = tmp_path / "vault"
    repo = JsonlNoteRepository(migrate_legacy_index(vault) / "index.jsonl")
    repo.add_note(
        Note(id="a", original_id="o", title="a note", body="b", type=NoteType.IDEA),
        HashingEmbedder().embed("a note"),
    )
    _block_import(monkeypatch, "mcp")
    code = main(["mcp", "-o", str(vault)])
    assert code == 1
    assert "mcp" in capsys.readouterr().err
    assert main(["mcp", "-o", str(tmp_path / "no-such-vault")]) == 1  # no index → error


def test_organize_text_writes_vault_graph_and_plan(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    summary = organize_text(_MESSY, source=_SOURCE, created=_CREATED, vault_dir=vault)

    assert summary.notes == 3  # 4 paragraphs, one exact duplicate skipped
    assert summary.skipped_duplicates == 1
    assert summary.graph_path.exists()
    assert summary.plan_path.exists()

    md_files = list(vault.glob("*.md"))
    assert any(p.name == "Plan.md" for p in md_files)
    note_files = [
        p
        for p in md_files
        if p.name
        not in ("Plan.md", "Masterplan.md", "Timeline.md", "Today.md", "_grandplan-guide.md")
    ]
    assert len(note_files) == summary.notes


def test_organize_text_creates_structural_part_of_edge(tmp_path: Path) -> None:
    # PR-G: placement attaches the action note under the similar, more-abstract goal — a part_of
    # edge, not just a `relates` similarity link. The report's structural count goes non-zero.
    from grandplan.core.placement import HeuristicPlacer

    text = (
        "Goal: launch the analytics product\n\nTask: finish the analytics product launch checklist"
    )
    summary = organize_text(
        text,
        source=_SOURCE,
        created=_CREATED,
        vault_dir=tmp_path / "vault",
        placer=HeuristicPlacer(part_of_threshold=0.15),
    )
    assert summary.report is not None
    assert summary.report.structural_edges >= 1
    data = json.loads(summary.graph_path.read_text(encoding="utf-8"))
    assert any(e["kind"] == "part_of" for e in data["edges"])


def test_organize_text_auto_extracts_entities(tmp_path: Path) -> None:
    # ROADMAP 3: organize surfaces people/org entities as `entity` nodes joined by `involves` edges.
    text = "Sync with Sarah Chen about the launch plan and ping @maria"
    summary = organize_text(text, source=_SOURCE, created=_CREATED, vault_dir=tmp_path / "vault")
    data = json.loads(summary.graph_path.read_text(encoding="utf-8"))
    entity_titles = {n["title"] for n in data["nodes"] if n.get("type") == "entity"}
    assert "Sarah Chen" in entity_titles
    assert any(e["kind"] == "involves" for e in data["edges"])


def test_graph_json_matches_committed_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    summary = organize_text(_MESSY, source=_SOURCE, created=_CREATED, vault_dir=vault)
    data = json.loads(summary.graph_path.read_text(encoding="utf-8"))
    assert len(data["nodes"]) == summary.notes


def test_main_organize_file_returns_zero_and_writes_outputs(tmp_path: Path) -> None:
    src = tmp_path / "notes.txt"
    src.write_text(_MESSY, encoding="utf-8")
    vault = tmp_path / "vault"

    # `--no-llm` keeps this a hermetic smoke test of the CLI wiring (the LLM default would require a
    # running Ollama, which CI does not provide); LLM-default behavior is covered by other tests.
    code = main(["organize", str(src), "-o", str(vault), "--no-llm"])

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
    note = next(
        p
        for p in vault.glob("*.md")
        if p.name
        not in ("Plan.md", "Masterplan.md", "Timeline.md", "Today.md", "_grandplan-guide.md")
    )
    assert "# STUB TITLE" in note.read_text(encoding="utf-8")


def test_main_llm_default_fails_loud_without_ollama(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # PR-F (RC1): the local model is the DEFAULT and is required — with no Ollama the command must
    # FAIL LOUD (exit 1, actionable error, nothing written), never silently emit keyword garbage.
    src = tmp_path / "n.txt"
    src.write_text("Buy milk and eggs", encoding="utf-8")
    vault = tmp_path / "vault"

    _block_import(monkeypatch, "ollama")
    code = main(["organize", str(src), "-o", str(vault)])  # no flag → LLM is the default
    assert code == 1
    err = capsys.readouterr().err
    assert "--no-llm" in err  # tells the user how to proceed
    assert not (vault / "Plan.md").exists()  # nothing written on failure


def test_main_no_llm_uses_offline_baseline(tmp_path: Path) -> None:
    # `--no-llm` is the deliberate offline path: the deterministic baseline, no model needed.
    src = tmp_path / "n.txt"
    src.write_text("Buy milk and eggs", encoding="utf-8")
    vault = tmp_path / "vault"

    code = main(["organize", str(src), "-o", str(vault), "--no-llm"])
    assert code == 0
    assert (vault / "Plan.md").exists()


def test_main_embeddings_flag_reports_missing_dependency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "n.txt"
    src.write_text("Buy milk and eggs", encoding="utf-8")
    vault = tmp_path / "vault"

    # `--no-llm` so the missing *embeddings* dependency is what surfaces, independent of whether a
    # local Ollama is available (CI has neither); the LLM path is tested separately.
    _block_import(monkeypatch, "sentence_transformers")
    code = main(["organize", str(src), "-o", str(vault), "--embeddings", "--no-llm"])
    assert code == 1
    assert "sentence-transformers" in capsys.readouterr().err


def test_main_gui_without_pyside_reports_missing_dependency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _block_import(monkeypatch, "PySide6")
    code = main(["gui", "-o", str(tmp_path / "vault")])
    assert code == 1
    assert "PySide6" in capsys.readouterr().err


def test_gui_init_and_open_scaffold_and_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `gui --init --open` scaffolds the vault + opens Obsidian, then launches the GUI. run_app and the
    # Obsidian launcher are stubbed so the test never opens a real window (and works without PySide6).
    monkeypatch.setattr("grandplan.app.gui.run_app", lambda **_: 0)
    opened: list[Path] = []
    monkeypatch.setattr(
        "grandplan.adapters.obsidian_open.open_in_obsidian",
        lambda vault_dir: opened.append(vault_dir) or True,
    )
    vault = tmp_path / "v"
    assert main(["gui", "-o", str(vault), "--init", "--open"]) == 0
    assert (vault / "graph.json").exists()  # --init scaffolded the vault
    assert (vault / ".obsidian" / "workspace.json").exists()  # opens on the graph
    assert opened == [vault]  # --open launched the Obsidian opener


def test_ask_answers_from_the_vault_with_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # `grandplan ask` (SPEC-AGENT-KB P1): retrieval-grounded, read-only Q&A. The model transport is
    # stubbed so the test is hermetic; retrieval + wiring + output formatting are real.
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    src = tmp_path / "n.txt"
    src.write_text("we decided to use postgres for the backend", encoding="utf-8")
    vault = tmp_path / "vault"
    assert main(["organize", str(src), "-o", str(vault), "--no-llm"]) == 0

    import grandplan.adapters.kb_ask as kb_ask

    monkeypatch.setattr(
        kb_ask,
        "_ollama_chat",
        lambda model, prompt: '{"answer": "Postgres.", "sources": []}',
    )
    assert main(["ask", "which database did I pick?", "-o", str(vault)]) == 0
    out = capsys.readouterr().out
    assert "Postgres." in out


def test_ask_without_index_reports_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    assert main(["ask", "anything?", "-o", str(tmp_path / "empty")]) == 1
    assert "no index" in capsys.readouterr().err


def test_ask_degrades_to_retrieval_only_without_a_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ollama down / no model pulled: still useful — print the top matching notes, clearly labeled.
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    src = tmp_path / "n.txt"
    src.write_text("we decided to use postgres for the backend", encoding="utf-8")
    vault = tmp_path / "vault"
    assert main(["organize", str(src), "-o", str(vault), "--no-llm"]) == 0

    import grandplan.adapters.kb_ask as kb_ask

    def _down(model: str, prompt: str) -> str:
        raise RuntimeError("ollama not running")

    monkeypatch.setattr(kb_ask, "_ollama_chat", _down)
    assert main(["ask", "what did we decide about the postgres backend?", "-o", str(vault)]) == 0
    out = capsys.readouterr().out
    assert "postgres" in out.lower()  # the matching note is surfaced
    assert "no local model" in out.lower()  # and the degradation is explicit, never silent


def test_chat_answers_shows_notes_and_quits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # `grandplan chat`: multi-turn REPL — a question gets a grounded answer with sources, /show
    # prints the full note under discussion, /quit leaves. Transport stubbed; wiring + IO real.
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    src = tmp_path / "n.txt"
    src.write_text("we decided to use postgres for the backend", encoding="utf-8")
    vault = tmp_path / "vault"
    assert main(["organize", str(src), "-o", str(vault), "--no-llm"]) == 0

    import grandplan.adapters.kb_ask as kb_ask
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository

    note_id = JsonlNoteRepository(migrate_legacy_index(vault) / "index.jsonl").notes()[0].id
    reply = '{"answer": "Postgres.", "sources": ["%s"]}' % note_id
    monkeypatch.setattr(kb_ask, "_ollama_chat", lambda model, prompt: reply)

    # The REPL uses the STREAMING seam for plain questions; the fake streams the same reply in
    # small chunks so the live-typing path (AnswerStreamFilter → terminal) is exercised end-to-end.
    def fake_stream(model: str, prompt: str, on_delta: Callable[[str], None]) -> str:
        for i in range(0, len(reply), 5):
            on_delta(reply[i : i + 5])
        return reply

    monkeypatch.setattr(kb_ask, "_ollama_chat_stream", fake_stream)
    lines = iter(["what did we decide about the postgres backend?", f"/show {note_id}", "/quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    assert main(["chat", "-o", str(vault)]) == 0
    out = capsys.readouterr().out
    assert "Postgres." in out  # the grounded answer, printed via the streamed deltas
    assert '{"answer"' not in out  # JSON syntax never reaches the terminal
    assert f"[{note_id}]" in out  # cited source
    assert "postgres for the backend" in out  # /show printed the full note body


def _plan_json(model: str, prompt: str) -> str:
    # Echo back the first retrieved note id as a source, like a well-behaved model would — so the
    # approved-plan test can assert the builds_on edge (containment keeps only retrieved ids).
    ids = re.findall(r"id=(\w+)", prompt)
    sources = f'["{ids[0]}"]' if ids else "[]"
    return (
        '{"title": "Postgres migration plan", "summary": "Move the backend to postgres.", '
        f'"steps": ["set up postgres", "migrate data"], "sources": {sources}}}'
    )


def _chat_plan_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, confirm: str
) -> tuple[Path, str]:
    """Drive `chat` through `/plan` + a confirmation answer; return (vault, captured stdout)."""
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    src = tmp_path / "n.txt"
    src.write_text("we decided to use postgres for the backend", encoding="utf-8")
    vault = tmp_path / "vault"
    assert main(["organize", str(src), "-o", str(vault), "--no-llm"]) == 0

    import grandplan.adapters.kb_ask as kb_ask

    monkeypatch.setattr(kb_ask, "_ollama_chat", _plan_json)
    lines = iter(["/plan postgres backend", confirm, "/quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    assert main(["chat", "-o", str(vault)]) == 0
    return vault, ""


def _index_notes(vault: Path) -> tuple:
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository

    return JsonlNoteRepository(migrate_legacy_index(vault) / "index.jsonl").notes()


def test_chat_plan_approved_writes_a_project_note_with_checklist(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # #39 stage 2: /plan drafts from the vault, an explicit "y" applies it append-only — the plan
    # lands as a PROJECT note with the organizer's own `- [ ]` checklist convention, and the
    # vault markdown re-renders so it is immediately visible in Obsidian.
    vault, _ = _chat_plan_run(tmp_path, monkeypatch, confirm="y")
    out = capsys.readouterr().out
    assert "PLAN: Postgres migration plan" in out  # previewed before the gate
    assert "plan saved to the vault" in out
    notes = _index_notes(vault)
    plan = next(n for n in notes if n.title == "Postgres migration plan")
    source = next(n for n in notes if n.id != plan.id)
    assert plan.type.value == "project"
    assert "- [ ] set up postgres" in plan.body
    rendered = list(vault.rglob("*.md"))
    assert any("Postgres migration plan" in p.read_text(encoding="utf-8") for p in rendered)
    # The plan is wired into the graph: builds_on edge to the source note it drew from.
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository

    edges = JsonlNoteRepository(migrate_legacy_index(vault) / "index.jsonl").edges()
    assert any(
        e.source_id == plan.id and e.target_id == source.id and e.kind.value == "builds_on"
        for e in edges
    )


def test_chat_plan_rejected_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The review gate is the contract (#39): anything except an explicit yes leaves ZERO trace.
    vault, _ = _chat_plan_run(tmp_path, monkeypatch, confirm="n")
    out = capsys.readouterr().out
    assert "discarded — nothing written." in out
    assert len(_index_notes(vault)) == 1  # only the captured note; no plan, no original, no edge


def test_chat_improve_approved_applies_edit_rejected_leaves_no_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # #36 (user-directed ONLY): /improve <id> drafts an improvement to the ONE named note; "y"
    # applies it as an append-only edit event (history preserved), anything else writes nothing.
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    src = tmp_path / "n.txt"
    src.write_text("we decided to use postgres for the backend", encoding="utf-8")
    vault = tmp_path / "vault"
    assert main(["organize", str(src), "-o", str(vault), "--no-llm"]) == 0

    import grandplan.adapters.kb_ask as kb_ask
    from grandplan.core.index_location import migrate_legacy_index
    from grandplan.core.note_store import JsonlNoteRepository

    index = migrate_legacy_index(vault) / "index.jsonl"
    note_id = JsonlNoteRepository(index).notes()[0].id
    monkeypatch.setattr(
        kb_ask,
        "_ollama_chat",
        lambda model, prompt: (
            '{"title": "Postgres backend decision", "body": "Cleaned body.", '
            '"tags": ["database"], "rationale": "tightened"}'
        ),
    )
    lines = iter([f"/improve {note_id}", "n", f"/improve {note_id}", "y", "/quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    assert main(["chat", "-o", str(vault)]) == 0
    out = capsys.readouterr().out
    assert "IMPROVE" in out and "discarded — nothing written." in out and "note improved" in out
    reopened = JsonlNoteRepository(index)
    current = reopened.current_note(note_id)
    assert current is not None and current.title == "Postgres backend decision"
    stored = reopened.get_note(note_id)
    assert stored is not None and stored.title != current.title  # append-only: creation intact
    assert sum(1 for e in reopened.history_of(note_id) if e.kind == "edit") == 1  # ONE edit (the y)


def test_chat_without_index_reports_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    assert main(["chat", "-o", str(tmp_path / "empty")]) == 1
    assert "no index" in capsys.readouterr().err


def test_gui_fast_is_default_and_thorough_opts_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Fast capture is the DEFAULT; --thorough opts back into 3-calls-inline; --fast stays accepted
    # for compatibility. Background enrichment (#38) is OPT-IN via --enrich: by default a capture
    # organizes inline and then NOTHING else runs (user decision 2026-07-04 — no autonomous
    # post-save LLM passes).
    seen: list[dict[str, object]] = []
    monkeypatch.setattr("grandplan.app.gui.run_app", lambda **kw: seen.append(kw) or 0)
    assert main(["gui", "-o", str(tmp_path / "v")]) == 0
    assert main(["gui", "-o", str(tmp_path / "v"), "--fast"]) == 0
    assert main(["gui", "-o", str(tmp_path / "v"), "--thorough"]) == 0
    assert main(["gui", "-o", str(tmp_path / "v"), "--enrich"]) == 0
    assert seen[0]["fast"] is True  # default
    assert seen[1]["fast"] is True  # compat flag
    assert seen[2]["fast"] is False  # explicit opt-out
    assert seen[0]["enrich"] is False  # default: no background LLM work after a save
    assert seen[1]["enrich"] is False
    assert seen[3]["enrich"] is True  # --enrich opts in, and only then


def test_gui_kb_model_is_configurable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The tray chat used to hardcode the KB default (qwen2.5:14b): a user who pulled a smaller
    # KB model (e.g. qwen2.5:7b — the sane choice next to a resident capture model) could not
    # make the GUI use it, so every chat turn burned a 404 and fell back to the capture model.
    seen: list[dict[str, object]] = []
    monkeypatch.setattr("grandplan.app.gui.run_app", lambda **kw: seen.append(kw) or 0)
    assert main(["gui", "-o", str(tmp_path / "v")]) == 0
    assert main(["gui", "-o", str(tmp_path / "v"), "--kb-model", "qwen2.5:7b"]) == 0
    assert seen[0]["kb_model"] is None  # default: the KB agent's own default (with fallback)
    assert seen[1]["kb_model"] == "qwen2.5:7b"


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


def test_gui_serve_params_flow_to_run_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # --serve (unified mode) must hand the phone-server host/port/token to run_app so the tray app
    # can host /capture routed through its single writer.
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    seen: list[dict[str, object]] = []
    monkeypatch.setattr("grandplan.app.gui.run_app", lambda **kw: seen.append(kw) or 0)
    assert (
        main(["gui", "-o", str(tmp_path / "v"), "--serve", "--port", "9999", "--token", "sekret"])
        == 0
    )
    assert seen[0]["serve"] is True
    assert seen[0]["serve_port"] == 9999
    assert seen[0]["serve_token"] == "sekret"
    assert seen[0]["serve_host"] == "127.0.0.1"
    # Without --serve the phone server stays off — the plain desktop GUI is unchanged.
    assert main(["gui", "-o", str(tmp_path / "v")]) == 0
    assert seen[1]["serve"] is False


def test_gui_serve_requires_token_for_non_localhost(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Hosting phone capture on a routable host without a shared secret would let anyone on the LAN
    # POST into the vault — refuse it, same rule as `up`/`serve`.
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GRANDPLAN_TOKEN", raising=False)
    monkeypatch.setattr("grandplan.app.gui.run_app", lambda **kw: 0)
    code = main(["gui", "-o", str(tmp_path / "v"), "--serve", "--host", "192.168.1.5"])
    assert code == 1
    assert "token" in capsys.readouterr().err


def test_up_embeddings_without_dep_fails_fast(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # `up --embeddings` must fail fast with install guidance (not organize the first phone capture
    # on a half-configured embedder) — same contract as the GUI.
    import importlib.util as ilu

    real_find_spec = ilu.find_spec
    monkeypatch.setattr(
        ilu,
        "find_spec",
        lambda name, *a, **k: None if name == "sentence_transformers" else real_find_spec(name),
    )
    code = main(["up", "-o", str(tmp_path / "v"), "--embeddings", "--dry-run"])
    assert code == 1
    assert "sentence-transformers" in capsys.readouterr().err


# -- capture-check input diagnostics -------------------------------------------------------------

from grandplan.cli import _capture_check_deps  # noqa: E402


def test_capture_check_deps_flags_missing_required_backend() -> None:
    # pynput + pyperclip missing (only the optional uiautomation present) → NOT ok, MISSING shown.
    report, ok = _capture_check_deps(lambda mod: object() if mod == "uiautomation" else None)
    assert ok is False
    assert "MISSING" in report
    assert "pynput" in report and "pyperclip" in report


def test_capture_check_deps_ok_when_required_present_optional_absent() -> None:
    # Required backends present; the optional uiautomation may be absent and that's still OK.
    report, ok = _capture_check_deps(
        lambda mod: object() if mod in {"pynput", "pyperclip"} else None
    )
    assert ok is True
    assert "absent" in report  # uiautomation reported as optional/absent, not a failure


def test_capture_check_command_reports_missing_deps_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # With no input backends importable, `capture-check` must fail clearly with the install hint
    # (and never reach the interactive pynput/clipboard steps).
    import importlib.util as _il

    monkeypatch.setattr(_il, "find_spec", lambda name, *a, **k: None)
    assert main(["capture-check"]) == 1
    out = capsys.readouterr().out
    assert "MISSING" in out
    assert ".[windows]" in out


def test_resolve_token_prefers_explicit_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    from grandplan.cli import _resolve_token

    monkeypatch.setenv("GRANDPLAN_TOKEN", "from-env")
    assert _resolve_token("from-arg") == "from-arg"  # explicit --token wins over the env var


def test_resolve_token_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from grandplan.cli import _resolve_token

    monkeypatch.setenv("GRANDPLAN_TOKEN", "from-env")
    assert _resolve_token("") == "from-env"  # no --token → GRANDPLAN_TOKEN keeps it off the cmdline


def test_resolve_token_empty_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from grandplan.cli import _resolve_token

    monkeypatch.delenv("GRANDPLAN_TOKEN", raising=False)
    assert _resolve_token("") == ""  # neither set → no auth (localhost-trust default)
