"""Tests for the external index location + legacy migration (keeps the index out of synced vaults)."""

from __future__ import annotations

from pathlib import Path

import pytest

from grandplan.core.index_location import index_dir, migrate_legacy_index


def test_index_dir_is_outside_the_vault_and_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    vault = tmp_path / "OneDrive" / "GrandNotes"
    first = index_dir(vault)
    assert first == index_dir(vault)  # deterministic
    assert (tmp_path / "home") in first.parents  # lives under GRANDPLAN_HOME
    assert vault not in first.parents  # NOT inside the (synced) vault
    assert index_dir(tmp_path / "OtherVault") != first  # per-vault


def test_migrate_moves_legacy_index_out_of_the_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    (vault / ".grandplan").mkdir(parents=True)
    (vault / ".grandplan" / "index.jsonl").write_text('{"kind":"note"}', encoding="utf-8")

    target = migrate_legacy_index(vault)

    assert (target / "index.jsonl").read_text(encoding="utf-8") == '{"kind":"note"}'
    assert not (vault / ".grandplan").exists()  # moved, not left behind to keep syncing


def test_migrate_is_noop_when_external_index_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    (vault / ".grandplan").mkdir(parents=True)
    target = index_dir(vault)
    target.mkdir(parents=True)
    (target / "index.jsonl").write_text("already-migrated", encoding="utf-8")

    migrate_legacy_index(vault)

    assert (target / "index.jsonl").read_text(encoding="utf-8") == "already-migrated"  # untouched
    assert (vault / ".grandplan").exists()  # legacy left alone — external already present


def test_migrate_is_noop_without_a_legacy_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    vault.mkdir()
    assert migrate_legacy_index(vault) == index_dir(vault)  # returns target, does not raise
