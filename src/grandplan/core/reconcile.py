"""Reconciler — classify a new note vs related notes and maintain consistency (US-10, #12).

Classification is a **Strategy** behind the port (ADR-0007): a `RelationshipClassifier` maps
`(new proposal, candidate note, similarity) → Relationship`. The deterministic `SimilarityClassifier`
baseline reproduces the original behaviour (DUPLICATE vs RELATED bands) and is the default, so the
offline core stays gated and existing behaviour is unchanged. A richer, LLM-backed classifier
(`adapters.llm_reconciler`) proposes `builds_on` / `refines` / `supersedes` / `contradicts` behind
the same interface, with a deterministic fallback.

Review-first & lossless: the reconciler only *proposes* candidates and a relationship; the human
decides link / merge / supersede / keep-both. Nothing is auto-resolved, and no stored note is ever
mutated — `supersedes`/`contradicts` are expressed as typed edges (+ a needs-review status set at
creation), which the Planner projects (ADR-0007), keeping the append-only invariant (QAS-2) intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from grandplan.core.models import EdgeKind, Note, NoteStatus, ProposedNote
from grandplan.core.ports import NoteRepository

_DEFAULT_DUPLICATE_THRESHOLD = 0.90


class Relationship(str, Enum):
    """How a new note relates to an existing one (SPEC §11.2)."""

    RELATED = "related"
    DUPLICATE = "duplicate"
    BUILDS_ON = "builds_on"
    REFINES = "refines"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"


# How each relationship is recorded as a typed edge (new note → existing note). DUPLICATE has no
# edge: it is the merge path (US-6), surfaced for the human, never auto-written.
RELATIONSHIP_EDGE_KIND: dict[Relationship, EdgeKind | None] = {
    Relationship.RELATED: EdgeKind.RELATES,
    Relationship.BUILDS_ON: EdgeKind.BUILDS_ON,
    Relationship.REFINES: EdgeKind.REFINES,
    Relationship.SUPERSEDES: EdgeKind.SUPERSEDES,
    Relationship.CONTRADICTS: EdgeKind.CONTRADICTS,
    Relationship.DUPLICATE: None,
}


@dataclass(frozen=True)
class RelatedCandidate:
    """An existing note a new capture resembles, with its similarity and classification.

    `suggested_status` (Slice B) is a status change the new note implies for THIS existing note
    (e.g. the capture completes it → `done`, or obsoletes it → `superseded`) — proposed by the
    context-aware reconciler, surfaced for review, applied append-only on approval. None = no change.
    """

    note: Note
    score: float
    relationship: Relationship
    suggested_status: NoteStatus | None = None


@dataclass(frozen=True)
class ReconcileProposal:
    """Ranked candidates for the human to act on (link / merge / supersede / keep-both)."""

    candidates: tuple[RelatedCandidate, ...]

    @property
    def is_probable_duplicate(self) -> bool:
        return any(c.relationship is Relationship.DUPLICATE for c in self.candidates)

    @property
    def related_notes(self) -> tuple[Note, ...]:
        """Notes classified as plainly RELATED (backward-compatible accessor)."""
        return tuple(c.note for c in self.candidates if c.relationship is Relationship.RELATED)

    @property
    def requires_review(self) -> bool:
        """A contradiction was detected: the new note should land as `needs-review` (never auto)."""
        return any(c.relationship is Relationship.CONTRADICTS for c in self.candidates)

    def links(self) -> tuple[tuple[Note, EdgeKind], ...]:
        """The typed edges to record on approval (every non-duplicate candidate)."""
        out: list[tuple[Note, EdgeKind]] = []
        for candidate in self.candidates:
            kind = RELATIONSHIP_EDGE_KIND[candidate.relationship]
            if kind is not None:
                out.append((candidate.note, kind))
        return tuple(out)

    def status_changes(self) -> tuple[tuple[Note, NoteStatus], ...]:
        """Proposed status changes to EXISTING related notes (Slice B), applied append-only on approval."""
        return tuple(
            (candidate.note, candidate.suggested_status)
            for candidate in self.candidates
            if candidate.suggested_status is not None
        )


class RelationshipClassifier(Protocol):
    """Classify how a new proposed note relates to one existing candidate note (Strategy)."""

    def classify(self, new: ProposedNote, candidate: Note, score: float) -> Relationship: ...


class SimilarityClassifier:
    """Deterministic baseline: DUPLICATE above the duplicate threshold, else RELATED."""

    def __init__(self, *, duplicate_threshold: float = _DEFAULT_DUPLICATE_THRESHOLD) -> None:
        self._dup = duplicate_threshold

    def classify(self, new: ProposedNote, candidate: Note, score: float) -> Relationship:
        return Relationship.DUPLICATE if score >= self._dup else Relationship.RELATED


class Reconciler(Protocol):
    """Classify a new note against the existing notes, ranked by embedding similarity."""

    def reconcile(
        self, proposed: ProposedNote, embedding: tuple[float, ...], repo: NoteRepository
    ) -> ReconcileProposal: ...


class SimilarityReconciler:
    """Rank candidates by cosine similarity, then classify each via the injected Strategy."""

    def __init__(
        self,
        *,
        link_threshold: float = 0.30,
        duplicate_threshold: float = _DEFAULT_DUPLICATE_THRESHOLD,
        limit: int = 5,
        classifier: RelationshipClassifier | None = None,
        llm_top_k: int = 2,
    ) -> None:
        if not 0.0 <= link_threshold <= duplicate_threshold <= 1.0:
            raise ValueError("require 0 <= link_threshold <= duplicate_threshold <= 1")
        if llm_top_k < 0:
            raise ValueError("llm_top_k must be >= 0")
        self._link = link_threshold
        self._limit = limit
        self._baseline = SimilarityClassifier(duplicate_threshold=duplicate_threshold)
        self._rich = classifier  # optional richer (e.g. LLM) classifier; None = baseline only
        self._llm_top_k = llm_top_k

    def reconcile(
        self, proposed: ProposedNote, embedding: tuple[float, ...], repo: NoteRepository
    ) -> ReconcileProposal:
        ranked = repo.most_similar(embedding, limit=self._limit, threshold=self._link)
        candidates: list[RelatedCandidate] = []
        for rank, (note, score) in enumerate(ranked):
            # Two-tier linking: the richer (LLM) classifier runs only on the top-k most-similar
            # candidates — where duplicate/supersede/contradict actually occur — which bounds LLM
            # calls per capture (CPU-friendly); the rest get the cheap deterministic baseline.
            classifier: RelationshipClassifier = self._baseline
            if self._rich is not None and rank < self._llm_top_k:
                classifier = self._rich
            candidates.append(
                RelatedCandidate(
                    note=note, score=score, relationship=classifier.classify(proposed, note, score)
                )
            )
        return ReconcileProposal(tuple(candidates))
