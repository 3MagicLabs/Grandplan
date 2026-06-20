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


def test_up_hotkey_shows_in_banner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Force pynput "present" so the test is hermetic (CI installs no optional extras).
    import importlib.machinery
    import importlib.util

    real = importlib.util.find_spec
    fake = importlib.machinery.ModuleSpec("pynput", loader=None)
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name: fake if name == "pynput" else real(name)
    )
    code = main(["up", "-o", str(tmp_path / "v"), "--hotkey", "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "global hotkey: <ctrl>+<alt>+g" in out


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
