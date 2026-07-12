"""Review session — the human-in-the-loop controller behind the GUI (US-4).

Pure orchestration over the core pipeline: `start_review` runs propose + assess and returns the
display state plus an immutable handle; the UI shows it; `approve` commits (optionally linking the
detected related notes), and `discard` does nothing (US-4 — the raw capture stays in the inbox).
No UI/Qt dependency here, so the review logic is fully unit-tested; the PySide6 view binds to these.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from grandplan.core.edit_detect import EditDetector
from grandplan.core.models import (
    Note,
    NoteEdit,
    NoteStatus,
    NoteType,
    Original,
    ProposedNote,
    Source,
    apply_edit,
)
from grandplan.core.pipeline import Assessment, CaptureResult, assess, commit, propose
from grandplan.core.placement import Placement, Placer, record_placement
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
    # PR-C: the capture is a detail edit to an existing note.
    is_edit: bool = False
    edit_target_title: str = ""
    edit_summary: str = ""  # human-readable, e.g. "due → Q3; title → CV"
    # Slice B: status changes this new note implies for EXISTING related notes, applied on approval.
    proposed_updates: tuple[tuple[str, str], ...] = ()  # (existing note title, new status value)
    body: str = ""  # the organizer's proposed note body — shown + editable before approval


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
class ProposedEdit:
    """A proposed field edit on an existing note (PR-C), detected from a capture + a match."""

    target: Note
    edit: NoteEdit
    score: float

    def summary(self) -> str:
        """Human-readable change list, e.g. `due → Q3; title → CV`."""
        return "; ".join(f"{field} → {value}" for field, value in self.edit.changes())


@dataclass(frozen=True)
class EditResult:
    """The outcome of an approved edit: an `edit` event, no new note (PR-C/ADR-0008)."""

    original: Original
    target: Note
    edit: NoteEdit


@dataclass(frozen=True)
class PendingReview:
    """An immutable handle to a capture awaiting the user's approve/discard decision."""

    original: Original
    proposed: ProposedNote
    assessment: Assessment
    related: tuple[Note, ...]
    state: ReviewState
    update: StatusUpdate | None = None  # set when the capture is a status update (PR-B)
    edit: ProposedEdit | None = None  # set when the capture is a detail edit (PR-C)
    placement: Placement | None = None  # proposed structural edges for a new note (PR-G)


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
    edit_detector: EditDetector | None = None,
    placer: Placer | None = None,
    match_threshold: float = _DEFAULT_MATCH_THRESHOLD,
) -> PendingReview:
    """Capture + organize + reconcile; return display state for review (nothing committed yet).

    Precedence **status > edit > new note**: if `detector` recognises update-intent and confidently
    matches a note, the review is a **status update** (PR-B); else if `edit_detector` recognises a
    field edit and matches, it is an **edit** (PR-C); otherwise it is a new note. Both reuse the same
    similarity match. With neither detector, behaviour is unchanged.
    """
    original, proposed = propose(text, source, created, organizer=organizer, originals=originals)
    assessment = assess(proposed, embedder=embedder, repo=repo, reconciler=reconciler)
    proposal = assessment.proposal
    # Match an update/edit against the existing notes using the embedding of the **verbatim capture**
    # (not the organizer's reorganized proposal): the user's literal words are what should locate the
    # note they mean — robust even when an LLM organizer rewrites the title (e.g. a retitle capture).
    match_embedding = (
        embedder.embed(original.text)
        if (detector is not None or edit_detector is not None)
        else None
    )
    update = _detect_update(
        original.text, match_embedding, repo, detector=detector, match_threshold=match_threshold
    )
    edit = (
        None
        if update is not None
        else _detect_edit(
            original.text,
            match_embedding,
            repo,
            detector=edit_detector,
            match_threshold=match_threshold,
        )
    )
    # PR-G: when the capture is a NEW note (not a status/edit update), propose its structural place
    # in the graph (parent + prerequisites) now — recorded on approve. Runs against the repo before
    # the new note exists, so it can't be its own parent.
    placement = (
        placer.place(proposed, assessment.embedding, repo)
        if placer is not None and update is None and edit is None
        else None
    )
    related = proposal.related_notes
    links = tuple(
        (candidate.relationship.value, candidate.note.title)
        for candidate in proposal.candidates
        if candidate.relationship is not Relationship.DUPLICATE
    )
    # Slice B: status changes this new note implies for existing notes — shown in the dialog and
    # applied on approve. Only when it's a NEW note (a status/edit-update capture doesn't add edges).
    proposed_updates = (
        tuple((note.title, status.value) for note, status in proposal.status_changes())
        if update is None and edit is None
        else ()
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
        is_edit=edit is not None,
        edit_target_title=edit.target.title if edit is not None else "",
        edit_summary=edit.summary() if edit is not None else "",
        proposed_updates=proposed_updates,
        body=proposed.body,
    )
    return PendingReview(
        original=original,
        proposed=proposed,
        assessment=assessment,
        related=related,
        state=state,
        update=update,
        edit=edit,
        placement=placement,
    )


def _best_match(
    embedding: tuple[float, ...] | None, repo: NoteRepository, match_threshold: float
) -> tuple[Note, float] | None:
    """The single most-similar note above `match_threshold` (the capture-driven update/edit target)."""
    if embedding is None:
        return None
    matches = repo.most_similar(embedding, limit=1, threshold=match_threshold)
    return matches[0] if matches else None


def _detect_update(
    text: str,
    embedding: tuple[float, ...] | None,
    repo: NoteRepository,
    *,
    detector: UpdateDetector | None,
    match_threshold: float,
) -> StatusUpdate | None:
    """Propose a status change when the capture is update-intent + a confident match (PR-B).

    Fail-safe: no detector, no intent, or no match above `match_threshold` → None (normal new-note
    flow, no note touched). Idempotent: if the match's derived status already equals the detected
    target, propose nothing (mirrors `set_status`'s no-op-on-equal, PR-A).
    """
    if detector is None:
        return None
    status = detector.detect(text)
    if status is None:
        return None
    match = _best_match(embedding, repo, match_threshold)
    if match is None:
        return None
    target, score = match
    if repo.status_of(target.id) is status:
        return None
    return StatusUpdate(target=target, status=status, score=score)


def _detect_edit(
    text: str,
    embedding: tuple[float, ...] | None,
    repo: NoteRepository,
    *,
    detector: EditDetector | None,
    match_threshold: float,
) -> ProposedEdit | None:
    """Propose a field edit when the capture is edit-intent + a confident match (PR-C).

    Fail-safe and idempotent like `_detect_update`: no detector / intent / match → None, and an edit
    that would not change the matched note's derived state proposes nothing.
    """
    if detector is None:
        return None
    edit = detector.detect(text)
    if edit is None:
        return None
    match = _best_match(embedding, repo, match_threshold)
    if match is None:
        return None
    target, score = match
    current = repo.current_note(target.id)
    if current is None or apply_edit(current, edit) == current:
        return None
    return ProposedEdit(target=target, edit=edit, score=score)


@dataclass(frozen=True)
class ReviewEdits:
    """Human edits to a proposed NEW note, made in the review UI before approval (desktop or phone).

    Every field is optional — None means "keep the organizer's proposal". Applied to `pending.proposed`
    right before commit, so the saved note (and its content-addressed id) reflect the human's version."""

    title: str | None = None
    body: str | None = None
    tags: tuple[str, ...] | None = None
    note_type: str | None = None  # a NoteType value (e.g. "task"); unknown values are ignored


def _apply_edits(proposed: ProposedNote, edits: ReviewEdits) -> ProposedNote:
    """Return a copy of `proposed` with the human's non-None edits applied (blank title/type ignored)."""
    result = proposed
    if edits.title is not None and edits.title.strip():
        result = replace(result, title=edits.title.strip())
    if edits.body is not None:
        result = replace(result, body=edits.body.strip())
    if edits.tags is not None:
        result = replace(result, tags=tuple(edits.tags))
    if edits.note_type is not None:
        try:
            note_type = NoteType(edits.note_type)
        except ValueError:
            note_type = (
                None  # an unknown type string → keep the proposed type, don't crash approval
            )
        if note_type is not None:
            result = replace(result, type=note_type)
    return result


def approve(
    pending: PendingReview,
    *,
    repo: NoteRepository,
    vault: VaultWriter,
    link_related: bool = True,
    edits: ReviewEdits | None = None,
) -> CaptureResult | StatusUpdateResult | EditResult:
    """Commit the review: a `status` event (PR-B), an `edit` event (PR-C), else a new note.

    An approved update/edit appends an event and creates **no** new note and **no** vault file — the
    matched note is never mutated (append-only/lossless, ADR-0007/0008). Each event is stamped with
    the capture's `created` (the no-hidden-clock timestamp). The raw capture stays in the inbox.
    """
    occurred = pending.original.created
    update = pending.update
    if update is not None:
        # Record the triggering capture's text on the event, so the note's History shows WHAT the
        # update said (a status update creates no note, so otherwise its content would be invisible).
        repo.set_status(
            update.target.id, update.status, at=occurred, detail=pending.original.text.strip()
        )
        return StatusUpdateResult(
            original=pending.original, target=update.target, status=update.status
        )
    edit = pending.edit
    if edit is not None:
        repo.record_edit(edit.target.id, edit.edit, at=occurred)
        return EditResult(original=pending.original, target=edit.target, edit=edit.edit)
    proposal = pending.assessment.proposal
    links = proposal.links() if link_related else ()
    status = NoteStatus.NEEDS_REVIEW if proposal.requires_review else NoteStatus.INBOX
    # Apply the human's review edits (title/body/tags/type) to the proposal before committing — the
    # relationships/status-changes come from the reconciliation assessment and are unaffected.
    proposed = pending.proposed if edits is None else _apply_edits(pending.proposed, edits)
    result = commit(
        pending.original,
        proposed,
        pending.assessment,
        repo=repo,
        vault=vault,
        links=links,
        status=status,
    )
    # PR-G: record the proposed structural edges (part_of/depends_on) after the note exists.
    record_placement(repo, pending.placement, result.note.id)
    # Slice B: apply the status changes this new note implies for EXISTING related notes — append-only
    # `status` events (the existing notes are never mutated), idempotent, stamped with the capture's
    # `created`. The human already approved them by approving this review.
    for note, new_status in proposal.status_changes():
        repo.set_status(note.id, new_status, at=occurred)
    return result


def discard(pending: PendingReview) -> None:
    """Discard a pending review: nothing is written to the index or vault (US-4).

    The raw capture remains in the inbox (OriginalStore) and can be reprocessed later.
    """
    _ = pending
    return None
