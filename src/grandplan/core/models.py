"""Core domain models for grandplan.

An `Original` is a captured selection preserved **verbatim** — immutable, never mutated
after capture (the lossless guarantee, SPEC US-2 / QAS-2 / §6d). A `Note` is the organized,
approved atomic note that *derives from* an Original (referencing it, never replacing it).
`Edge`s are typed, directional relationships between notes. The schema is "plan-ready"
(horizons, status, contexts, collections, typed edges) per SPEC §11.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class Source:
    """Where a captured selection came from."""

    app: str
    title: str = ""
    uri: str = ""


@dataclass(frozen=True)
class Original:
    """A captured selection, preserved verbatim. Immutable.

    `id` is a deterministic content hash, so identical captures collapse to one
    record (natural exact-duplicate handling) without any clock or randomness.
    """

    id: str
    text: str
    source: Source
    created: str  # ISO-8601 timestamp, supplied by the caller (no hidden clock)

    @staticmethod
    def capture(text: str, source: Source, created: str) -> Original:
        """Create an Original with a deterministic content-addressed id."""
        parts = (text, source.app, source.title, source.uri, created)
        digest = hashlib.sha256(b"\x00".join(p.encode("utf-8") for p in parts))
        return Original(id=digest.hexdigest(), text=text, source=source, created=created)


class NoteType(str, Enum):
    """The kind of a note; actionable types (task/project/goal) drive planning."""

    IDEA = "idea"
    REFERENCE = "reference"
    TASK = "task"
    PROJECT = "project"
    GOAL = "goal"
    DECISION = "decision"
    QUESTION = "question"
    ENTITY = "entity"


class NoteStatus(str, Enum):
    """Lifecycle status; `needs_review` flags unresolved contradictions (SPEC §11.2)."""

    INBOX = "inbox"
    NEXT = "next"
    ACTIVE = "active"
    DONE = "done"
    NEEDS_REVIEW = "needs-review"
    SUPERSEDED = "superseded"


class Horizon(str, Enum):
    """Altitude of a note (SPEC §11.1): masterplan at the top, action at the bottom."""

    MASTERPLAN = "masterplan"
    GOAL = "goal"
    PROJECT = "project"
    ACTION = "action"


class EdgeKind(str, Enum):
    """Typed relationships. Dependency/sequence kinds form the DAG the Planner sorts."""

    DEPENDS_ON = "depends_on"
    BLOCKS = "blocks"
    NEXT = "next"
    PART_OF = "part_of"
    RELATES = "relates"
    BUILDS_ON = "builds_on"
    REFINES = "refines"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    WAITING_ON = "waiting_on"
    INVOLVES = "involves"


@dataclass(frozen=True)
class ProposedNote:
    """An Organizer's proposal, before human approval. References the verbatim Original."""

    original_id: str
    title: str
    body: str
    type: NoteType
    tags: tuple[str, ...] = ()
    horizon: Horizon = Horizon.ACTION


@dataclass(frozen=True)
class Note:
    """An approved, organized atomic note. Immutable; derives from an Original."""

    id: str
    original_id: str
    title: str
    body: str
    type: NoteType
    status: NoteStatus = NoteStatus.INBOX
    horizon: Horizon = Horizon.ACTION
    tags: tuple[str, ...] = ()
    contexts: tuple[str, ...] = ()
    due: str | None = None
    collections: tuple[str, ...] = ()

    @staticmethod
    def from_proposed(proposed: ProposedNote) -> Note:
        """Approve a proposal into a Note with a deterministic content-addressed id."""
        parts = (proposed.original_id, proposed.title, proposed.body, proposed.type.value)
        digest = hashlib.sha256(b"\x00".join(p.encode("utf-8") for p in parts)).hexdigest()
        return Note(
            id=digest[:16],
            original_id=proposed.original_id,
            title=proposed.title,
            body=proposed.body,
            type=proposed.type,
            tags=proposed.tags,
            horizon=proposed.horizon,
        )


@dataclass(frozen=True)
class Edge:
    """A typed, directional relationship between two notes."""

    source_id: str
    target_id: str
    kind: EdgeKind
