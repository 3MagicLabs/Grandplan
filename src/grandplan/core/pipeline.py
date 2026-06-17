"""Capture pipeline: propose → assess → (human approves) → commit.

- `propose`: capture the original verbatim into the inbox (never lost, US-2) and return an
  Organizer proposal.
- `assess`: embed the proposal and reconcile it against existing notes — surfacing related
  notes to link and likely duplicates to review (US-5/US-6/US-10) *before* anything is written.
- `commit`: on approval, index the note (with its embedding), record the approved RELATES
  links, and write the vault file.
- Discarding = simply not calling `commit`: nothing enters the index or vault (US-4), while
  the raw capture stays in the inbox.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from grandplan.core.models import (
    Edge,
    EdgeKind,
    Note,
    NoteStatus,
    Original,
    ProposedNote,
    Source,
)
from grandplan.core.ports import Embedder, NoteRepository, Organizer, VaultWriter
from grandplan.core.reconcile import Reconciler, ReconcileProposal
from grandplan.core.store import OriginalStore


@dataclass(frozen=True)
class Assessment:
    """A proposal's embedding plus how it reconciles against existing notes."""

    embedding: tuple[float, ...]
    proposal: ReconcileProposal


@dataclass(frozen=True)
class CaptureResult:
    """The outcome of committing an approved note."""

    original: Original
    note: Note
    path: Path
    links: tuple[Edge, ...]


def propose(
    text: str,
    source: Source,
    created: str,
    *,
    organizer: Organizer,
    originals: OriginalStore,
) -> tuple[Original, ProposedNote]:
    """Capture the original (inbox) and return a proposed note for review (US-3/US-4)."""
    original = Original.capture(text, source, created)
    originals.add(original)
    return original, organizer.organize(original)


def assess(
    proposed: ProposedNote,
    *,
    embedder: Embedder,
    repo: NoteRepository,
    reconciler: Reconciler,
) -> Assessment:
    """Embed the proposal and reconcile it against existing notes (US-5/US-6/US-10)."""
    embedding = embedder.embed(f"{proposed.title}\n{proposed.body}")
    return Assessment(embedding=embedding, proposal=reconciler.reconcile(proposed, embedding, repo))


def commit(
    original: Original,
    proposed: ProposedNote,
    assessment: Assessment,
    *,
    repo: NoteRepository,
    vault: VaultWriter,
    links: tuple[tuple[Note, EdgeKind], ...] = (),
    status: NoteStatus = NoteStatus.INBOX,
) -> CaptureResult:
    """Approve: index the note (with the approved typed links + status), write the vault file.

    `links` are the approved (target note, edge kind) pairs from reconciliation (US-10): RELATES,
    BUILDS_ON, REFINES, SUPERSEDES, CONTRADICTS. `status` lets a contradiction land the new note as
    `needs-review`. No existing note is mutated — supersede/contradict are expressed as edges and a
    creation-time status, preserving the append-only/lossless invariant (ADR-0007).
    """
    note = Note.from_proposed(proposed)
    if status is not note.status:
        note = replace(note, status=status)
    repo.add_note(note, assessment.embedding)
    edges = tuple(Edge(note.id, target.id, kind) for target, kind in links)
    for edge in edges:
        repo.add_edge(edge)
    targets = {target.id: target for target, _ in links}
    path = vault.write(note, original, edges, targets=targets)
    return CaptureResult(original=original, note=note, path=path, links=edges)
