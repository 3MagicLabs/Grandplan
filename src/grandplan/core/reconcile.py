"""Reconciler — link a new note to related notes and flag likely duplicates (US-5/US-6/US-10).

Baseline classifies by embedding-similarity bands: RELATED (propose a link) vs DUPLICATE
(propose review/merge). Richer classifications (builds_on / refines / supersedes / contradicts)
arrive with a future LLM-backed reconciler behind the same interface; the data model already
supports them (SPEC §11.2). Review-first: this proposes candidates; the human decides
link / merge / create-new — nothing is auto-resolved.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from grandplan.core.models import Note
from grandplan.core.ports import NoteRepository


class Relationship(str, Enum):
    """How a new note relates to an existing one (baseline bands)."""

    RELATED = "related"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class RelatedCandidate:
    """An existing note a new capture resembles, with its similarity and classification."""

    note: Note
    score: float
    relationship: Relationship


@dataclass(frozen=True)
class ReconcileProposal:
    """Ranked candidates for the human to act on (link / merge / create-new)."""

    candidates: tuple[RelatedCandidate, ...]

    @property
    def is_probable_duplicate(self) -> bool:
        return any(c.relationship is Relationship.DUPLICATE for c in self.candidates)

    @property
    def related_notes(self) -> tuple[Note, ...]:
        return tuple(c.note for c in self.candidates if c.relationship is Relationship.RELATED)


class Reconciler(Protocol):
    """Classify a new note's embedding against the existing notes."""

    def reconcile(
        self, embedding: tuple[float, ...], repo: NoteRepository
    ) -> ReconcileProposal: ...


class SimilarityReconciler:
    """Cosine-similarity reconciler with link / duplicate thresholds."""

    def __init__(
        self, *, link_threshold: float = 0.30, duplicate_threshold: float = 0.90, limit: int = 5
    ) -> None:
        if not 0.0 <= link_threshold <= duplicate_threshold <= 1.0:
            raise ValueError("require 0 <= link_threshold <= duplicate_threshold <= 1")
        self._link = link_threshold
        self._dup = duplicate_threshold
        self._limit = limit

    def reconcile(self, embedding: tuple[float, ...], repo: NoteRepository) -> ReconcileProposal:
        candidates = tuple(
            RelatedCandidate(
                note=note,
                score=score,
                relationship=(
                    Relationship.DUPLICATE if score >= self._dup else Relationship.RELATED
                ),
            )
            for note, score in repo.most_similar(embedding, limit=self._limit, threshold=self._link)
        )
        return ReconcileProposal(candidates)
