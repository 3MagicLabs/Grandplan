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

from grandplan.core.models import EdgeKind, Note, ProposedNote
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
    """An existing note a new capture resembles, with its similarity and classification."""

    note: Note
    score: float
    relationship: Relationship


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
    ) -> None:
        if not 0.0 <= link_threshold <= duplicate_threshold <= 1.0:
            raise ValueError("require 0 <= link_threshold <= duplicate_threshold <= 1")
        # `duplicate_threshold` only configures the default classifier; passing it alongside a
        # custom classifier would silently do nothing, so reject that combination explicitly.
        if classifier is not None and duplicate_threshold != _DEFAULT_DUPLICATE_THRESHOLD:
            raise ValueError("duplicate_threshold is unused when a custom classifier is provided")
        self._link = link_threshold
        self._limit = limit
        self._classifier: RelationshipClassifier = classifier or SimilarityClassifier(
            duplicate_threshold=duplicate_threshold
        )

    def reconcile(
        self, proposed: ProposedNote, embedding: tuple[float, ...], repo: NoteRepository
    ) -> ReconcileProposal:
        candidates = tuple(
            RelatedCandidate(
                note=note,
                score=score,
                relationship=self._classifier.classify(proposed, note, score),
            )
            for note, score in repo.most_similar(embedding, limit=self._limit, threshold=self._link)
        )
        return ReconcileProposal(candidates)
