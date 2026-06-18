"""Core domain models for grandplan.

An `Original` is a captured selection preserved **verbatim** — immutable, never mutated
after capture (the lossless guarantee, SPEC US-2 / QAS-2 / §6d). A `Note` is the organized,
approved atomic note that *derives from* an Original (referencing it, never replacing it).
`Edge`s are typed, directional relationships between notes. The schema is "plan-ready"
(horizons, status, contexts, collections, typed edges) per SPEC §11.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import Enum
from typing import Literal

from grandplan.core.resources import Resource


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
    resources: tuple[Resource, ...] = ()  # extracted links/files/images/placeholders (PR-D)


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
    resources: tuple[Resource, ...] = ()  # referenced/expected artifacts (PR-D); not part of the id

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
            resources=proposed.resources,
        )


@dataclass(frozen=True)
class Edge:
    """A typed, directional relationship between two notes."""

    source_id: str
    target_id: str
    kind: EdgeKind


# Order in which a NoteEdit's set fields are rendered/summarised (stable, deterministic).
_EDITABLE_FIELDS: tuple[str, ...] = ("title", "body", "tags", "due")


@dataclass(frozen=True)
class NoteEdit:
    """A change to a subset of a note's editable fields (PR-C, ADR-0008).

    `None` means "leave this field unchanged" for every field; recorded as an `edit` *event* and
    applied on derivation, so the stored note is never mutated and its `id` never changes. Clearing
    a field (setting `due` back to `None`) is out of scope — `None` is always "unchanged".
    """

    title: str | None = None
    body: str | None = None
    tags: tuple[str, ...] | None = None
    due: str | None = None

    def is_empty(self) -> bool:
        """True when no field is set (applying it would be a no-op)."""
        return all(getattr(self, field) is None for field in _EDITABLE_FIELDS)

    def changes(self) -> tuple[tuple[str, object], ...]:
        """The (field, new value) pairs this edit sets, in a stable order."""
        return tuple(
            (field, getattr(self, field))
            for field in _EDITABLE_FIELDS
            if getattr(self, field) is not None
        )


def apply_edit(note: Note, edit: NoteEdit) -> Note:
    """Return a new Note with `edit`'s set fields applied (same `id` — identity is stable).

    `None` on any field of `edit` means "leave unchanged"; the note's content-addressed id is never
    recomputed, so an edit changes a note's fields without changing its identity.
    """
    return replace(
        note,
        title=note.title if edit.title is None else edit.title,
        body=note.body if edit.body is None else edit.body,
        tags=note.tags if edit.tags is None else edit.tags,
        due=note.due if edit.due is None else edit.due,
    )


@dataclass(frozen=True)
class NoteEvent:
    """One entry in a note's history — its "git log". A status change, a field edit, or an attached
    resource (PR-C/PR-E)."""

    note_id: str
    kind: Literal["status", "edit", "resource"]  # a status change, a field edit, or an attachment
    at: str | None = None  # caller-supplied timestamp (the capture's `created`); None if unknown
    status: NoteStatus | None = None
    edit: NoteEdit | None = None
    resource: Resource | None = None

    def summary(self) -> str:
        """A compact human-readable description, e.g. `status → done` or `+file: resume.pdf`."""
        if self.kind == "status" and self.status is not None:
            return f"status → {self.status.value}"
        if self.kind == "edit" and self.edit is not None:
            parts = ", ".join(f"{field} → {value}" for field, value in self.edit.changes())
            return f"edit: {parts}" if parts else "edit"
        if self.kind == "resource" and self.resource is not None:
            return f"+{self.resource.kind.value}: {self.resource.ref}"
        return self.kind
