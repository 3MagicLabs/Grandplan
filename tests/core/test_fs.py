"""Tests for the skip-if-identical write helper (incremental-projection fix, audit P1.1/P1.4)."""

from __future__ import annotations

from pathlib import Path

from grandplan.core.fs import write_text_if_changed


def test_writes_when_the_file_is_absent(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    assert write_text_if_changed(path, "hello") is True
    assert path.read_text(encoding="utf-8") == "hello"


def test_skips_and_leaves_mtime_untouched_when_identical(tmp_path: Path) -> None:
    # The OneDrive guarantee: a re-write of identical content must not touch the file at all, so a
    # cloud-synced vault does not re-upload it. No sleep needed — the skip path never opens the file.
    path = tmp_path / "a.txt"
    write_text_if_changed(path, "hello")
    mtime = path.stat().st_mtime_ns
    assert write_text_if_changed(path, "hello") is False
    assert path.stat().st_mtime_ns == mtime  # untouched


def test_writes_when_the_content_changed(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    write_text_if_changed(path, "hello")
    assert write_text_if_changed(path, "world") is True
    assert path.read_text(encoding="utf-8") == "world"


def test_write_survives_a_directory_in_the_way(tmp_path: Path) -> None:
    # An unreadable target (here, a directory) must not swallow into a silent no-op — it falls
    # through to the write, which raises loudly rather than pretending success.
    victim = tmp_path / "d"
    victim.mkdir()
    try:
        write_text_if_changed(victim, "x")
    except OSError:
        return  # expected: the write attempt raised, not a silent False
    raise AssertionError("expected an OSError writing over a directory")
