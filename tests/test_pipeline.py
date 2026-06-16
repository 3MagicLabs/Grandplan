"""End-to-end pipeline tests: propose → assess → commit, plus discard / link / dedup."""

from __future__ import annotations

from pathlib import Path

from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Source
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.pipeline import assess, commit, propose
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore
from grandplan.core.vault import MarkdownVaultWriter

_SOURCE = Source(app="Notepad", title="note.txt")
_CREATED = "2026-06-15T12:00:00Z"
_ORGANIZER = HeuristicOrganizer()
_EMBEDDER = HashingEmbedder()
_RECONCILER = SimilarityReconciler()


def test_commit_writes_note_and_preserves_original(tmp_path: Path) -> None:
    originals = InMemoryOriginalStore()
    repo = InMemoryNoteRepository()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    text = "Project kickoff\nschedule the first planning meeting"

    original, proposed = propose(text, _SOURCE, _CREATED, organizer=_ORGANIZER, originals=originals)
    assessment = assess(proposed, embedder=_EMBEDDER, repo=repo, reconciler=_RECONCILER)
    result = commit(original, proposed, assessment, repo=repo, vault=vault)

    assert repo.get_note(result.note.id) is not None
    written = result.path.read_text(encoding="utf-8")
    assert text in written  # verbatim original embedded
    assert "# Project kickoff" in written


def test_discard_writes_nothing_to_index_or_vault(tmp_path: Path) -> None:
    originals = InMemoryOriginalStore()
    repo = InMemoryNoteRepository()
    vault_dir = tmp_path / "vault"

    original, _ = propose(
        "a discarded thought", _SOURCE, _CREATED, organizer=_ORGANIZER, originals=originals
    )

    assert originals.get(original.id) is not None  # raw capture retained (US-2)
    assert repo.notes() == ()  # nothing in the index (US-4)
    assert not vault_dir.exists()  # nothing written to the vault (US-4)


def test_related_note_is_detected_and_linked(tmp_path: Path) -> None:
    originals = InMemoryOriginalStore()
    repo = InMemoryNoteRepository()
    vault = MarkdownVaultWriter(tmp_path / "vault")

    o1, p1 = propose(
        "machine learning notes about neural networks",
        _SOURCE,
        _CREATED,
        organizer=_ORGANIZER,
        originals=originals,
    )
    first = commit(
        o1,
        p1,
        assess(p1, embedder=_EMBEDDER, repo=repo, reconciler=_RECONCILER),
        repo=repo,
        vault=vault,
    )

    o2, p2 = propose(
        "neural networks and deep learning study",
        _SOURCE,
        _CREATED,
        organizer=_ORGANIZER,
        originals=originals,
    )
    a2 = assess(p2, embedder=_EMBEDDER, repo=repo, reconciler=_RECONCILER)
    assert first.note in a2.proposal.related_notes  # US-5 detection

    second = commit(o2, p2, a2, repo=repo, vault=vault, link_to=a2.proposal.related_notes)
    assert any((e.source_id, e.target_id) == (second.note.id, first.note.id) for e in repo.edges())
    assert f"[[{first.note.id}]]" in second.path.read_text(encoding="utf-8")


def test_exact_duplicate_capture_is_flagged(tmp_path: Path) -> None:
    originals = InMemoryOriginalStore()
    repo = InMemoryNoteRepository()
    vault = MarkdownVaultWriter(tmp_path / "vault")
    text = "exact same capture about quarterly planning goals"

    o1, p1 = propose(text, _SOURCE, _CREATED, organizer=_ORGANIZER, originals=originals)
    commit(
        o1,
        p1,
        assess(p1, embedder=_EMBEDDER, repo=repo, reconciler=_RECONCILER),
        repo=repo,
        vault=vault,
    )

    _, p2 = propose(text, _SOURCE, _CREATED, organizer=_ORGANIZER, originals=originals)
    a2 = assess(p2, embedder=_EMBEDDER, repo=repo, reconciler=_RECONCILER)
    assert a2.proposal.is_probable_duplicate  # US-6 review-before-clutter
