"""Capture pipeline: propose → (human approves) → commit.

`propose` captures the original verbatim into the capture log (inbox) immediately — so a
capture is never lost (US-2) — and returns an Organizer proposal. `commit` runs only on
approval: it creates the Note, embeds it, stores it in the index, and writes the vault file.
Discarding means simply not calling `commit`: nothing lands in the index or vault (US-4),
while the raw capture is retained.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from grandplan.core.models import Edge, Note, Original, ProposedNote, Source
from grandplan.core.ports import Embedder, NoteRepository, Organizer, VaultWriter
from grandplan.core.store import OriginalStore


@dataclass(frozen=True)
class CaptureResult:
    """The outcome of committing an approved note."""

    original: Original
    note: Note
    path: Path


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


def commit(
    original: Original,
    proposed: ProposedNote,
    *,
    embedder: Embedder,
    repo: NoteRepository,
    vault: VaultWriter,
    links: tuple[Edge, ...] = (),
) -> CaptureResult:
    """Approve a proposal: index the note (with its embedding) and write the vault file."""
    note = Note.from_proposed(proposed)
    repo.add_note(note, embedder.embed(f"{note.title}\n{note.body}"))
    path = vault.write(note, original, links)
    return CaptureResult(original=original, note=note, path=path)
