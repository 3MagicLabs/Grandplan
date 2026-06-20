"""Tests for folder-watch capture — scan_folder enqueues a directive per new file (pure logic)."""

from __future__ import annotations

from pathlib import Path

from grandplan.adapters.folder_watch import scan_folder
from grandplan.core.directive import InMemoryDirectiveStore


def _drop(folder: Path, name: str, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def _scan(folder: Path, store: InMemoryDirectiveStore, seen: set[str]) -> list[str]:
    return scan_folder(
        folder,
        store,
        created="2026-06-20",
        instruction="file it",
        playbook="capture-and-file",
        seen=seen,
    )


def test_scan_enqueues_a_directive_per_text_file(tmp_path: Path) -> None:
    _drop(tmp_path, "a.txt", "first idea")
    _drop(tmp_path, "b.md", "second idea")
    store, seen = InMemoryDirectiveStore(), set()
    ids = _scan(tmp_path, store, seen)
    assert len(ids) == 2
    assert {d.playbook for d in store.pending()} == {"capture-and-file"}


def test_scan_skips_already_seen_files(tmp_path: Path) -> None:
    _drop(tmp_path, "a.txt", "idea")
    store, seen = InMemoryDirectiveStore(), set()
    assert len(_scan(tmp_path, store, seen)) == 1
    # second scan: the file is in `seen` → nothing new
    assert _scan(tmp_path, store, seen) == []


def test_scan_ignores_non_capture_suffixes(tmp_path: Path) -> None:
    _drop(tmp_path, "data.json", "{}")
    _drop(tmp_path, "photo.png", "x")
    store, seen = InMemoryDirectiveStore(), set()
    assert _scan(tmp_path, store, seen) == []


def test_scan_skips_empty_files(tmp_path: Path) -> None:
    _drop(tmp_path, "empty.txt", "   \n")
    store, seen = InMemoryDirectiveStore(), set()
    assert _scan(tmp_path, store, seen) == []
    assert str((tmp_path / "empty.txt").resolve()) in seen  # marked seen, not retried


def test_scan_skips_undecodable_files(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "bad.txt").write_bytes(b"\xff\xfe\x00\x01not utf-8")
    store, seen = InMemoryDirectiveStore(), set()
    assert _scan(tmp_path, store, seen) == []  # undecodable → skipped, no directive
    assert str((tmp_path / "bad.txt").resolve()) in seen  # marked seen, not retried


def test_scan_missing_folder_is_noop(tmp_path: Path) -> None:
    store, seen = InMemoryDirectiveStore(), set()
    assert _scan(tmp_path / "nope", store, seen) == []


def test_scan_is_idempotent_on_identical_content_across_fresh_seen(tmp_path: Path) -> None:
    # Even with a fresh `seen`, identical content collapses to one directive (content-addressed id).
    _drop(tmp_path, "a.txt", "same content")
    store = InMemoryDirectiveStore()
    first = _scan(tmp_path, store, set())
    second = _scan(tmp_path, store, set())  # fresh seen → re-reads, but same id
    assert first == second
    assert len(store.all()) == 1
