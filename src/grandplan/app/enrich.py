"""Background enrichment (#38): restore LLM typed links + placement after a --fast capture.

`--fast` keeps only the organize call on the capture's critical path; the two enrichment calls
(contextual reconcile → typed links, placement → part_of/depends_on) are skipped inline. This
module re-derives them AFTER commit, off the critical path, so fast mode loses nothing long-term.

Execution model (single-writer, ADR-0006 / SPEC-AGENT-KB §3): `enrich_note` is a pure synchronous
function; the `CaptureCoordinator` runs it on its ONE worker thread, and only when the capture
queue is idle — enrichment never writes the repo concurrently with a capture and never delays one
(beyond an already-running enrichment call finishing).

Safety rules, in order:
- **Deleted** or **user-edited** notes are skipped (an edit means the stored embedding is stale —
  re-deriving links from it could attach wrong ones; the user's version always wins).
- Self-classification is dropped (the note ranks #1 in its own neighborhood → the reconciler sees
  it as a DUPLICATE of itself); DUPLICATE never auto-applies anyway — merge is a human decision.
- Everything is append-only edge addition, deduped; a failure (Ollama down, bad JSON) leaves the
  baseline edges exactly as committed. Notes left unenriched (e.g. app quit) keep their baseline;
  `regenerate` re-derives everything from scratch when wanted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from grandplan.core.models import Edge, ProposedNote
from grandplan.core.placement import Placer
from grandplan.core.ports import NoteRepository
from grandplan.core.reconcile import RELATIONSHIP_EDGE_KIND, Reconciler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnrichOutcome:
    """What one enrichment attempt did — surfaced in logs and (later) progress UI."""

    note_id: str
    outcome: str  # "enriched" | "skipped-deleted" | "skipped-user-edited" | "failed"
    edges_added: int = 0


def enrich_note(
    note_id: str,
    *,
    repo: NoteRepository,
    reconciler: Reconciler,
    placer: Placer,
) -> EnrichOutcome:
    """Re-derive typed links + structural placement for one committed note (append-only)."""
    note = repo.get_note(note_id)
    if note is None:
        return EnrichOutcome(note_id=note_id, outcome="skipped-deleted")
    if any(event.kind == "edit" for event in repo.history_of(note_id)):
        return EnrichOutcome(note_id=note_id, outcome="skipped-user-edited")
    embedding = repo.embedding_of(note_id)
    if embedding is None:
        return EnrichOutcome(note_id=note_id, outcome="failed")
    proposed = ProposedNote(
        original_id=note.original_id,
        title=note.title,
        body=note.body,
        type=note.type,
        tags=note.tags,
        horizon=note.horizon,
        resources=note.resources,
    )
    added = 0
    try:
        proposal = reconciler.reconcile(proposed, embedding, repo)
        for candidate in proposal.candidates:
            if candidate.note.id == note_id:
                continue  # the note itself (score 1.0 in its own neighborhood)
            kind = RELATIONSHIP_EDGE_KIND.get(candidate.relationship)
            if kind is None:
                continue  # DUPLICATE (merge is a human decision) / unmapped
            edge = Edge(note_id, candidate.note.id, kind)
            if edge not in repo.edges():
                repo.add_edge(edge)
                added += 1
        placement = placer.place(proposed, embedding, repo)
        if placement is not None:
            for edge in placement.edges(note_id):
                if (
                    edge.target_id != note_id
                    and repo.get_note(edge.target_id) is not None
                    and edge not in repo.edges()
                ):
                    repo.add_edge(edge)
                    added += 1
    except Exception as exc:  # noqa: BLE001 - model not pulled, Ollama down, bad JSON
        logger.warning("enrichment of %s failed (baseline links kept): %s", note_id, exc)
        return EnrichOutcome(note_id=note_id, outcome="failed", edges_added=added)
    return EnrichOutcome(note_id=note_id, outcome="enriched", edges_added=added)
