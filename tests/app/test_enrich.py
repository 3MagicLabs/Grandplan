"""Background enrichment (#38): restore LLM typed links + placement after a --fast capture.

`enrich_note` is the pure, synchronous unit (fakes here); the coordinator runs it on its ONE
worker thread, only when the capture queue is idle — the single-writer invariant (ADR-0006)
holds and captures always win. Enrichment is best-effort: any failure leaves the baseline
edges exactly as they were.
"""

from __future__ import annotations

from pathlib import Path

from grandplan.app.enrich import EnrichOutcome, enrich_note
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Edge, EdgeKind, Note, NoteEdit, NoteType, ProposedNote
from grandplan.core.placement import Placement
from grandplan.core.reconcile import (
    RelatedCandidate,
    Relationship,
    ReconcileProposal,
)
from grandplan.core.repository import InMemoryNoteRepository


def _repo() -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    embedder = HashingEmbedder()
    for note_id, title, body, note_type in (
        ("fresh", "postgres migration", "move the backend to postgres", NoteType.TASK),
        ("goal", "database modernization goal", "modernize storage", NoteType.GOAL),
        ("old", "postgres evaluation", "evaluated postgres earlier", NoteType.IDEA),
    ):
        note = Note(id=note_id, original_id=f"o-{note_id}", title=title, body=body, type=note_type)
        repo.add_note(note, embedder.embed(f"{title}\n{body}"))
    return repo


class _TypedReconciler:
    """Returns the note itself as DUPLICATE (self always ranks #1) + one typed candidate."""

    def reconcile(self, proposed: ProposedNote, embedding, repo):  # type: ignore[no-untyped-def]
        me = repo.get_note("fresh")
        other = repo.get_note("old")
        return ReconcileProposal(
            candidates=(
                RelatedCandidate(note=me, score=1.0, relationship=Relationship.DUPLICATE),
                RelatedCandidate(note=other, score=0.7, relationship=Relationship.BUILDS_ON),
            )
        )


class _GoalPlacer:
    def place(self, proposed: ProposedNote, embedding, repo):  # type: ignore[no-untyped-def]
        return Placement(parent_id="goal")


class _BoomReconciler:
    def reconcile(self, proposed, embedding, repo):  # type: ignore[no-untyped-def]
        raise RuntimeError("ollama down")


def test_enrich_adds_typed_and_placement_edges_skipping_self_and_duplicates(
    tmp_path: Path,
) -> None:
    repo = _repo()
    outcome = enrich_note("fresh", repo=repo, reconciler=_TypedReconciler(), placer=_GoalPlacer())
    assert outcome == EnrichOutcome(note_id="fresh", outcome="enriched", edges_added=2)
    edges = repo.edges()
    assert Edge("fresh", "old", EdgeKind.BUILDS_ON) in edges  # typed link restored
    assert Edge("fresh", "goal", EdgeKind.PART_OF) in edges  # placement restored
    # Self-classification (the note ranks #1 in its own neighborhood) must never become an edge.
    assert not any(e.source_id == e.target_id for e in edges)


def test_enrich_is_idempotent_on_existing_edges() -> None:
    repo = _repo()
    repo.add_edge(Edge("fresh", "old", EdgeKind.BUILDS_ON))  # baseline already had it
    outcome = enrich_note("fresh", repo=repo, reconciler=_TypedReconciler(), placer=_GoalPlacer())
    assert outcome.edges_added == 1  # only the placement edge was new


def test_enrich_skips_deleted_and_user_edited_notes() -> None:
    repo = _repo()
    repo.delete_note("fresh")
    assert enrich_note(
        "fresh", repo=repo, reconciler=_TypedReconciler(), placer=_GoalPlacer()
    ).outcome == "skipped-deleted"

    repo2 = _repo()
    repo2.record_edit("fresh", NoteEdit(title="user renamed me"))
    outcome = enrich_note("fresh", repo=repo2, reconciler=_TypedReconciler(), placer=_GoalPlacer())
    assert outcome.outcome == "skipped-user-edited"  # stale embedding — never clobber user work
    assert not repo2.edges()


def test_enrich_failure_leaves_baseline_untouched() -> None:
    repo = _repo()
    before = repo.edges()
    outcome = enrich_note("fresh", repo=repo, reconciler=_BoomReconciler(), placer=_GoalPlacer())
    assert outcome.outcome == "failed"
    assert repo.edges() == before  # graceful: the note simply keeps its baseline links


# -- coordinator integration: the SAME worker drains enrichment at idle priority -------------------


def _coordinator(tmp_path: Path, enrich=None):  # type: ignore[no-untyped-def]
    from grandplan.app.coordinator import CaptureCoordinator
    from grandplan.core.models import Source
    from grandplan.core.organize import HeuristicOrganizer
    from grandplan.core.reconcile import SimilarityReconciler
    from grandplan.core.store import InMemoryOriginalStore
    from grandplan.core.vault import MarkdownVaultWriter

    class _NoCapture:
        def capture(self) -> str | None:
            return None

    return CaptureCoordinator(
        capturer=_NoCapture(),
        organizer=HeuristicOrganizer(),
        embedder=HashingEmbedder(),
        reconciler=SimilarityReconciler(),
        repo=InMemoryNoteRepository(),
        originals=InMemoryOriginalStore(),
        vault=MarkdownVaultWriter(tmp_path / "vault"),
        review=lambda state: True,
        source=Source(app="test"),
        enrich=enrich,
    )


def test_coordinator_queues_dedupes_and_runs_enrichment(tmp_path: Path) -> None:
    ran: list[str] = []
    coord = _coordinator(tmp_path, enrich=lambda note_id: ran.append(note_id) or note_id)
    assert coord.submit_enrichment("n1") is True
    assert coord.submit_enrichment("n1") is False  # already queued → dedup
    assert coord.submit_enrichment("n2") is True
    assert coord.enrichment_pending() == 2
    assert coord.run_one_enrichment() == "n1"  # FIFO
    assert coord.run_one_enrichment() == "n2"
    assert coord.run_one_enrichment() is None  # drained
    assert ran == ["n1", "n2"] and coord.enrichment_pending() == 0


def test_coordinator_enrichment_off_and_failure_isolation(tmp_path: Path) -> None:
    off = _coordinator(tmp_path, enrich=None)
    assert off.submit_enrichment("n1") is False  # enrichment off → silently no-op
    assert off.run_one_enrichment() is None

    def boom(note_id: str) -> object:
        raise RuntimeError("enrichment exploded")

    fragile = _coordinator(tmp_path, enrich=boom)
    fragile.submit_enrichment("n1")
    assert fragile.run_one_enrichment() is None  # logged and dropped — worker never wedges
    assert fragile.enrichment_pending() == 0
