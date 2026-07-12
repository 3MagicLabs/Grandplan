"""Re-link a vault: add the similarity/typed edges between notes that already exist.

Capture reconciles each NEW note against the notes present *at that moment*. So notes imported from
another vault (or captured before their neighbours existed) can sit unconnected in the graph even
though they're similar. `relink_notes` fixes that WITHOUT re-organizing or re-embedding: it reconciles
every note against the others using its STORED embedding and records the edges the reconciler proposes.

Append-only + idempotent + safe: it never rewrites a note, a note never links to itself, and an edge
that already exists is skipped — so re-running adds nothing new. Pure over the repo (a Reconciler is
injected), so it's fully unit-tested; the CLI wraps it with a backup + re-projection.
"""

from __future__ import annotations

from grandplan.core.models import Edge, Note, ProposedNote
from grandplan.core.ports import NoteRepository
from grandplan.core.reconcile import Reconciler


def _as_proposed(note: Note) -> ProposedNote:
    """A ProposedNote view of an existing note, so the reconciler's classifier can inspect its fields."""
    return ProposedNote(
        original_id=note.original_id,
        title=note.title,
        body=note.body,
        type=note.type,
        tags=note.tags,
        horizon=note.horizon,
        resources=note.resources,
    )


def relink_notes(repo: NoteRepository, reconciler: Reconciler) -> int:
    """Reconcile every current note against the others by its stored embedding, adding any MISSING
    edges the reconciler proposes. Returns the number of edges added.

    A note is its own most-similar match, so self-edges are skipped; existing edges are skipped
    (idempotent). Notes with no stored embedding (shouldn't happen) are left alone."""
    existing = {(edge.source_id, edge.target_id) for edge in repo.edges()}
    added = 0
    for note in repo.current_notes():
        embedding = repo.embedding_of(note.id)
        if embedding is None:
            continue
        proposal = reconciler.reconcile(_as_proposed(note), embedding, repo)
        for target, kind in proposal.links():
            if target.id == note.id or (note.id, target.id) in existing:
                continue  # never self-link; never duplicate an existing edge
            repo.add_edge(Edge(note.id, target.id, kind))
            existing.add((note.id, target.id))
            added += 1
    return added
