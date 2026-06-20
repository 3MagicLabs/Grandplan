"""VaultWrite — a pure, offline, append-only write facade over the knowledge graph.

The write counterpart to ``VaultQuery`` (agent-operable vault, step 2). Lets an AI agent **enrich,
organize, and create** safely: every operation is an *event* reusing the PR-A…PR-G repository ops, so
no stored note or original is ever mutated and current state stays *derived* (QAS-2). It is pure (no
IO beyond the injected repo/originals/embedder) and offline (QAS-1), so it is fully unit-tested
without the optional ``mcp`` dep — the MCP server registers ``WRITE_TOOLS`` and routes ``call-tool``
through ``dispatch_write``.

Each method **validates inputs** (unknown note / bad enum / empty arg / self-loop → ``ValueError``
with a clear message) and returns ``{"ok": True, "applied": bool, ...}``. ``applied=False`` reports an
idempotent no-op (status unchanged, edit is a no-op, edge/resource already present, note already
exists) — the underlying repo ops are themselves idempotent and orphan-guarded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TypeVar

from grandplan.core.entities import (
    EntityExtractor,
    HeuristicEntityExtractor,
    materialize_entities,
)
from grandplan.core.models import (
    Edge,
    EdgeKind,
    Note,
    NoteEdit,
    NoteStatus,
    NoteType,
    Original,
    ProposedNote,
    Source,
)
from grandplan.core.ports import Embedder, NoteRepository
from grandplan.core.query import ToolSpec, _require_str, _schema
from grandplan.core.resources import Resource, ResourceKind
from grandplan.core.store import OriginalStore


@dataclass(frozen=True)
class VaultWrite:
    """Append-only write operations over a vault's repo + originals + embedder (agent-facing)."""

    repo: NoteRepository
    originals: OriginalStore
    embedder: Embedder
    entity_extractor: EntityExtractor = field(default_factory=HeuristicEntityExtractor)

    def set_status(self, note_id: str, status: str) -> dict[str, object]:
        """Set a note's lifecycle status (an event; the stored note is never mutated)."""
        self._require_note(note_id)
        new_status = _enum(NoteStatus, status, "status")
        applied = self.repo.status_of(note_id) is not new_status
        self.repo.set_status(note_id, new_status)
        return {"ok": True, "applied": applied, "note_id": note_id, "status": new_status.value}

    def record_edit(
        self,
        note_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
        due: str | None = None,
    ) -> dict[str, object]:
        """Edit a subset of a note's fields (title/body/tags/due) as an event (id stays stable)."""
        self._require_note(note_id)
        edit = NoteEdit(
            title=title,
            body=body,
            tags=tuple(tags) if tags is not None else None,
            due=due,
        )
        if edit.is_empty():
            raise ValueError("no fields to edit (set at least one of title/body/tags/due)")
        before = self.repo.current_note(note_id)
        self.repo.record_edit(note_id, edit)
        return {
            "ok": True,
            "applied": self.repo.current_note(note_id) != before,
            "note_id": note_id,
        }

    def add_resource(self, note_id: str, kind: str, ref: str, label: str = "") -> dict[str, object]:
        """Attach a referenced/expected artifact (link/image/file/placeholder) as an event."""
        self._require_note(note_id)
        resource_kind = _enum(ResourceKind, kind, "kind")
        if not ref:
            raise ValueError("missing required argument: ref")
        existing = {(r.kind, r.ref) for r in self.repo.resources_of(note_id)}
        applied = (resource_kind, ref) not in existing
        self.repo.add_resource(note_id, Resource(kind=resource_kind, ref=ref, label=label))
        return {"ok": True, "applied": applied, "note_id": note_id}

    def place(self, source_id: str, target_id: str, kind: str) -> dict[str, object]:
        """Place a typed structural edge (part_of/depends_on/blocks/…) between two existing notes."""
        self._require_note(source_id)
        self._require_note(target_id)
        if source_id == target_id:
            raise ValueError("cannot place an edge from a note to itself (self-loop)")
        edge = Edge(source_id, target_id, _enum(EdgeKind, kind, "kind"))
        applied = edge not in self.repo.edges()
        self.repo.add_edge(edge)
        return {"ok": True, "applied": applied, "source_id": source_id, "target_id": target_id}

    def propose_note(
        self,
        text: str,
        title: str,
        type: str,
        created: str,
        *,
        body: str = "",
        tags: list[str] | tuple[str, ...] = (),
    ) -> dict[str, object]:
        """Create a new note from agent-supplied text (append-only; verbatim original preserved).

        ``created`` is a caller-supplied ISO timestamp — no hidden clock (the original's id is content
        addressed over it, so identical proposals collapse to one note). The body defaults to the
        verbatim text. The note id is deterministic, so re-proposing identical input is idempotent.
        """
        if not text:
            raise ValueError("missing required argument: text")
        if not title:
            raise ValueError("missing required argument: title")
        if not created:
            raise ValueError("missing required argument: created")
        note_type = _enum(NoteType, type, "type")
        original = Original.capture(text, Source(app="agent"), created)
        self.originals.add(original)
        proposed = ProposedNote(
            original_id=original.id,
            title=title,
            body=body or text,
            type=note_type,
            tags=tuple(tags),
        )
        note = Note.from_proposed(proposed)
        applied = self.repo.current_note(note.id) is None
        self.repo.add_note(note, self.embedder.embed(f"{title}\n{body or text}"))
        return {"ok": True, "applied": applied, "note_id": note.id}

    def extract_entities(self, note_id: str) -> dict[str, object]:
        """Extract people/org entities from a note's verbatim text → `entity` nodes + `involves` edges.

        Reads the note's original text (richer than the title), runs the injected extractor (offline
        heuristic by default), and materializes each mention as an `entity` note joined by an
        `involves` edge. Append-only + idempotent: re-running adds nothing new (`applied=False`).
        """
        note = self.repo.current_note(note_id)
        if note is None:
            raise ValueError(f"unknown note: {note_id!r}")
        original = self.originals.get(note.original_id)
        # Extract from the verbatim original AND the (possibly edited/organized) title + body, so
        # entities surface whether they're in the raw capture or added later by an agent edit.
        text = "\n".join(
            part for part in (original.text if original else "", note.title, note.body) if part
        )
        mentions = self.entity_extractor.extract(text)
        before = len(self.repo.edges())
        entity_ids = materialize_entities(
            self.repo, self.originals, self.embedder, note_id, mentions
        )
        return {
            "ok": True,
            "applied": len(self.repo.edges()) > before,
            "note_id": note_id,
            "entities": [mention.name for mention in mentions],
            "entity_ids": list(entity_ids),
        }

    def _require_note(self, note_id: str) -> None:
        if not note_id:
            raise ValueError("missing required argument: note_id")
        if self.repo.current_note(note_id) is None:
            raise ValueError(f"unknown note: {note_id!r}")


_E = TypeVar("_E", bound=Enum)


def _enum(enum: type[_E], value: str, label: str) -> _E:
    """Parse ``value`` into ``enum`` or raise a ValueError naming the allowed values."""
    try:
        return enum(value)
    except ValueError:
        allowed = ", ".join(str(member.value) for member in enum)
        raise ValueError(f"invalid {label}: {value!r} (expected one of: {allowed})") from None


WRITE_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "set_status",
        "Set a note's status (inbox/next/active/done/needs-review/superseded). Append-only event.",
        _schema(
            {
                "note_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": [member.value for member in NoteStatus],
                },
            },
            ["note_id", "status"],
        ),
    ),
    ToolSpec(
        "record_edit",
        "Edit a note's title/body/tags/due. The note id stays stable; recorded as an event.",
        _schema(
            {
                "note_id": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "due": {"type": "string", "description": "ISO date, e.g. 2026-07-01"},
            },
            ["note_id"],
        ),
    ),
    ToolSpec(
        "add_resource",
        "Attach a referenced/expected artifact (link/image/file/placeholder) to a note.",
        _schema(
            {
                "note_id": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": [member.value for member in ResourceKind],
                },
                "ref": {"type": "string", "description": "URL, file path, or artifact description"},
                "label": {"type": "string"},
            },
            ["note_id", "kind", "ref"],
        ),
    ),
    ToolSpec(
        "place",
        "Place a typed structural edge (part_of/depends_on/blocks/next/…) between two notes.",
        _schema(
            {
                "source_id": {"type": "string"},
                "target_id": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": [member.value for member in EdgeKind],
                },
            },
            ["source_id", "target_id", "kind"],
        ),
    ),
    ToolSpec(
        "propose_note",
        "Create a new note from text (append-only; the verbatim text is preserved as the original).",
        _schema(
            {
                "text": {"type": "string", "description": "the verbatim source text"},
                "title": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": [member.value for member in NoteType],
                },
                "created": {"type": "string", "description": "ISO timestamp for the capture"},
                "body": {"type": "string", "description": "organized body (defaults to text)"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            ["text", "title", "type", "created"],
        ),
    ),
    ToolSpec(
        "extract_entities",
        "Extract people/org entities from a note → `entity` nodes + `involves` edges (append-only).",
        _schema({"note_id": {"type": "string"}}, ["note_id"]),
    ),
)


def dispatch_write(write: VaultWrite, name: str, arguments: dict[str, object]) -> object:
    """Route an MCP write tool call to the matching VaultWrite method (validates name + args)."""
    if name == "set_status":
        return write.set_status(
            _require_str(arguments, "note_id"), _require_str(arguments, "status")
        )
    if name == "record_edit":
        return write.record_edit(
            _require_str(arguments, "note_id"),
            title=_opt_str(arguments, "title"),
            body=_opt_str(arguments, "body"),
            tags=_opt_str_list(arguments, "tags"),
            due=_opt_str(arguments, "due"),
        )
    if name == "add_resource":
        return write.add_resource(
            _require_str(arguments, "note_id"),
            _require_str(arguments, "kind"),
            _require_str(arguments, "ref"),
            label=_opt_str(arguments, "label") or "",
        )
    if name == "place":
        return write.place(
            _require_str(arguments, "source_id"),
            _require_str(arguments, "target_id"),
            _require_str(arguments, "kind"),
        )
    if name == "propose_note":
        return write.propose_note(
            _require_str(arguments, "text"),
            _require_str(arguments, "title"),
            _require_str(arguments, "type"),
            _require_str(arguments, "created"),
            body=_opt_str(arguments, "body") or "",
            tags=_opt_str_list(arguments, "tags") or (),
        )
    if name == "extract_entities":
        return write.extract_entities(_require_str(arguments, "note_id"))
    raise ValueError(f"unknown tool: {name!r}")


def _opt_str(arguments: dict[str, object], key: str) -> str | None:
    value = arguments.get(key)
    return value if isinstance(value, str) and value else None


def _opt_str_list(arguments: dict[str, object], key: str) -> tuple[str, ...] | None:
    value = arguments.get(key)
    if not isinstance(value, (list, tuple)):
        return None
    return tuple(item for item in value if isinstance(item, str))
