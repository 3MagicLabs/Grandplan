"""Review session — the human-in-the-loop controller behind the GUI (US-4).

Pure orchestration over the core pipeline: `start_review` runs propose + assess and returns the
display state plus an immutable handle; the UI shows it; `approve` commits (optionally linking the
detected related notes), and `discard` does nothing (US-4 — the raw capture stays in the inbox).
No UI/Qt dependency here, so the review logic is fully unit-tested; the PySide6 view binds to these.
"""

from __future__ import annotations

from dataclasses import dataclass

from grandplan.core.models import Note, Original, ProposedNote, Source
from grandplan.core.pipeline import Assessment, CaptureResult, assess, commit, propose
from grandplan.core.ports import Embedder, NoteRepository, Organizer, VaultWriter
from grandplan.core.reconcile import Reconciler
from grandplan.core.store import OriginalStore


@dataclass(frozen=True)
class ReviewState:
    """Everything the review UI needs to display for one capture."""

    original_text: str
    title: str
    note_type: str
    tags: tuple[str, ...]
    related_titles: tuple[str, ...]
    is_probable_duplicate: bool


@dataclass(frozen=True)
class PendingReview:
    """An immutable handle to a capture awaiting the user's approve/discard decision."""

    original: Original
    proposed: ProposedNote
    assessment: Assessment
    related: tuple[Note, ...]
    state: ReviewState


def start_review(
    text: str,
    *,
    created: str,
    source: Source,
    organizer: Organizer,
    embedder: Embedder,
    reconciler: Reconciler,
    repo: NoteRepository,
    originals: OriginalStore,
) -> PendingReview:
    """Capture + organize + reconcile; return display state for review (nothing committed yet)."""
    original, proposed = propose(text, source, created, organizer=organizer, originals=originals)
    assessment = assess(proposed, embedder=embedder, repo=repo, reconciler=reconciler)
    related = assessment.proposal.related_notes
    state = ReviewState(
        original_text=original.text,
        title=proposed.title,
        note_type=proposed.type.value,
        tags=proposed.tags,
        related_titles=tuple(note.title for note in related),
        is_probable_duplicate=assessment.proposal.is_probable_duplicate,
    )
    return PendingReview(
        original=original, proposed=proposed, assessment=assessment, related=related, state=state
    )


def approve(
    pending: PendingReview,
    *,
    repo: NoteRepository,
    vault: VaultWriter,
    link_related: bool = True,
) -> CaptureResult:
    """Commit the reviewed note, optionally linking the detected related notes."""
    link_to = pending.related if link_related else ()
    return commit(
        pending.original,
        pending.proposed,
        pending.assessment,
        repo=repo,
        vault=vault,
        link_to=link_to,
    )


def discard(pending: PendingReview) -> None:
    """Discard a pending review: nothing is written to the index or vault (US-4).

    The raw capture remains in the inbox (OriginalStore) and can be reprocessed later.
    """
    _ = pending
    return None
