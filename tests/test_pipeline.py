"""End-to-end pipeline tests: propose → commit, and discard semantics."""

from __future__ import annotations

from pathlib import Path

from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Source
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.pipeline import commit, propose
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore
from grandplan.core.vault import MarkdownVaultWriter

_SOURCE = Source(app="Notepad", title="note.txt")
_CREATED = "2026-06-15T12:00:00Z"


def test_propose_then_commit_writes_note_and_preserves_original(tmp_path: Path) -> None:
    originals = InMemoryOriginalStore()
    repo = InMemoryNoteRepository()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    text = "Project kickoff\nschedule the first planning meeting"

    original, proposed = propose(
        text, _SOURCE, _CREATED, organizer=HeuristicOrganizer(), originals=originals
    )
    result = commit(original, proposed, embedder=HashingEmbedder(), repo=repo, vault=vault)

    assert originals.get(original.id) is not None
    assert repo.get_note(result.note.id) is not None
    written = result.path.read_text(encoding="utf-8")
    assert text in written  # verbatim original embedded in the note
    assert "# Project kickoff" in written


def test_discard_writes_nothing_to_index_or_vault(tmp_path: Path) -> None:
    originals = InMemoryOriginalStore()
    repo = InMemoryNoteRepository()
    vault_dir = tmp_path / "vault"

    original, _ = propose(
        "a discarded thought",
        _SOURCE,
        _CREATED,
        organizer=HeuristicOrganizer(),
        originals=originals,
    )

    # User discards: commit is never called.
    assert originals.get(original.id) is not None  # raw capture retained (US-2)
    assert repo.notes() == ()  # nothing in the index (US-4)
    assert not vault_dir.exists()  # nothing written to the vault (US-4)
