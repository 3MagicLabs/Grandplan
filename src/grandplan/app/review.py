"""Review session — the human-in-the-loop controller behind the GUI (US-4).

Pure orchestration over the core pipeline: `start_review` runs propose + assess and returns the
display state plus an immutable handle; the UI shows it; `approve` commits (optionally linking the
detected related notes), and `discard` does nothing (US-4 — the raw capture stays in the inbox).
No UI/Qt dependency here, so the review logic is fully unit-tested; the PySide6 view binds to these.
"""

from __future__ import annotations

from dataclasses import dataclass

from grandplan.core.models import Note, NoteStatus, Original, ProposedNote, Source
from grandplan.core.pipeline import Assessment, CaptureResult, assess, commit, propose
from grandplan.core.ports import Embedder, NoteRepository, Organizer, VaultWriter
from grandplan.core.reconcile import Reconciler, Relationship
from grandplan.core.store import OriginalStore
from grandplan.core.update_detect import UpdateDetector

# Minimum cosine similarity for a capture to be treated as an *update* to an existing note (PR-B).
# Higher than the reconciler's link threshold (0.30): a status change must target a confident match,
# and the human still approves it. Tunable; the LLM detector's verdict gates whether we look at all.
_DEFAULT_MATCH_THRESHOLD = 0.5


@dataclass(frozen=True)
class ReviewState:
    """Everything the review UI needs to display for one capture."""

    original_text: str
    title: str
    note_type: str
    tags: tuple[str, ...]
    related_titles: tuple[str, ...]
    is_probable_duplicate: bool
    requires_review: bool = False  # a contradiction was detected → lands as needs-review (US-10)
    links: tuple[tuple[str, str], ...] = ()  # (relationship, target title) for each non-duplicate
    # PR-B: the capture is a progress update to an existing note (not a new idea).
    is_status_update: bool = False
    update_target_title: str = ""  # the matched note this update applies to
    update_status: str = ""  # the proposed new status value (e.g. "done")


@dataclass(frozen=True)
class StatusUpdate:
    """A proposed status change on an existing note (PR-B), detected from a capture + a match."""

    target: Note
    status: NoteStatus
    score: float


@dataclass(frozen=True)
class StatusUpdateResult:
    """The outcome of an approved status update: a `status` event, no new note (PR-B/ADR-0008)."""

    original: Original
    target: Note
    status: NoteStatus


@dataclass(frozen=True)
class PendingReview:
    """An immutable handle to a capture awaiting the user's approve/discard decision."""

    original: Original
    proposed: ProposedNote
    assessment: Assessment
    related: tuple[Note, ...]
    state: ReviewState
    update: StatusUpdate | None = None  # set when the capture is an update to an existing note


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
    detector: UpdateDetector | None = None,
    match_threshold: float = _DEFAULT_MATCH_THRESHOLD,
) -> PendingReview:
    """Capture + organize + reconcile; return display state for review (nothing committed yet).

    PR-B: if `detector` recognises update-intent in the capture *and* it confidently matches an
    existing note, the review becomes a **status-update** proposal (`pending.update`) instead of a
    new note — the "commit a change" verb of ADR-0008. With no detector, behaviour is unchanged.
    """
    original, proposed = propose(text, source, created, organizer=organizer, originals=originals)
    assessment = assess(proposed, embedder=embedder, repo=repo, reconciler=reconciler)
    proposal = assessment.proposal
    update = _detect_update(
        original.text, assessment, repo, detector=detector, match_threshold=match_threshold
    )
    related = proposal.related_notes
    links = tuple(
        (candidate.relationship.value, candidate.note.title)
        for candidate in proposal.candidates
        if candidate.relationship is not Relationship.DUPLICATE
    )
    state = ReviewState(
        original_text=original.text,
        title=proposed.title,
        note_type=proposed.type.value,
        tags=proposed.tags,
        related_titles=tuple(note.title for note in related),
        is_probable_duplicate=proposal.is_probable_duplicate,
        requires_review=proposal.requires_review,
        links=links,
        is_status_update=update is not None,
        update_target_title=update.target.title if update is not None else "",
        update_status=update.status.value if update is not None else "",
    )
    return PendingReview(
        original=original,
        proposed=proposed,
        assessment=assessment,
        related=related,
        state=state,
        update=update,
    )


def _detect_update(
    text: str,
    assessment: Assessment,
    repo: NoteRepository,
    *,
    detector: UpdateDetector | None,
    match_threshold: float,
) -> StatusUpdate | None:
    """Propose a status change when the capture is update-intent + a confident match (PR-B).

    Considers at most one candidate (`limit=1`) above `match_threshold`.
    Fail-safe: no detector, no intent, or no match above `match_threshold` → None (normal new-note
    flow, no note touched). Idempotent: if the match's derived status already equals the detected
    target, propose nothing (mirrors `set_status`'s no-op-on-equal, PR-A).
    """
    if detector is None:
        return None
    status = detector.detect(text)
    if status is None:
        return None
    matches = repo.most_similar(assessment.embedding, limit=1, threshold=match_threshold)
    if not matches:
        return None
    target, score = matches[0]
    if repo.status_of(target.id) is status:
        return None
    return StatusUpdate(target=target, status=status, score=score)


def approve(
    pending: PendingReview,
    *,
    repo: NoteRepository,
    vault: VaultWriter,
    link_related: bool = True,
) -> CaptureResult | StatusUpdateResult:
    """Commit the review: a `status` event for an update (PR-B), else a new note.

    An approved update appends a `status` event (`repo.set_status`) and creates **no** new note and
    **no** vault file — the matched note is never mutated (append-only/lossless, ADR-0007/0008). The
    raw capture stays in the inbox regardless.
    """
    update = pending.update
    if update is not None:
        repo.set_status(update.target.id, update.status)
        return StatusUpdateResult(
            original=pending.original, target=update.target, status=update.status
        )
    proposal = pending.assessment.proposal
    links = proposal.links() if link_related else ()
    status = NoteStatus.NEEDS_REVIEW if proposal.requires_review else NoteStatus.INBOX
    return commit(
        pending.original,
        pending.proposed,
        pending.assessment,
        repo=repo,
        vault=vault,
        links=links,
        status=status,
    )


def discard(pending: PendingReview) -> None:
    """Discard a pending review: nothing is written to the index or vault (US-4).

    The raw capture remains in the inbox (OriginalStore) and can be reprocessed later.
    """
    _ = pending
    return None
