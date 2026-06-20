"""Entity extraction — turn people/org mentions into `entity` nodes + `involves` edges (ROADMAP 3).

A note often mentions the people and organizations it concerns ("ping Sarah Chen", "the Anthropic
deal", "@maria owns this"). This stage surfaces them as first-class `entity` notes joined to the
source note by an `involves` edge, so the graph becomes a people/org graph an agent can reason over
(who's involved in what) rather than just a pile of text.

It is a Strategy behind the `EntityExtractor` port (ADR-0003): the deterministic
`HeuristicEntityExtractor` is the offline default; a richer LLM adapter can propose the same shape
later. Append-only & safe (ADR-0008): materialization only *adds* entity notes + `involves` edges —
no stored note is mutated, ids are content-addressed by entity name so the same entity dedupes, and
both `add_note`/`add_edge` are idempotent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from grandplan.core.models import (
    Edge,
    EdgeKind,
    Note,
    NoteType,
    Original,
    ProposedNote,
    Source,
)
from grandplan.core.ports import Embedder, NoteRepository
from grandplan.core.store import OriginalStore

# A multi-word proper noun: two+ capitalized words in a row ("Sarah Chen", "Acme Robotics"). Requiring
# ≥2 consecutive capitalized words avoids matching every sentence-initial capital. Connector particles
# (and/&/of) are deliberately NOT bridged, so "John and Jane" stays two separate entities.
_PROPER_NOUN = re.compile(r"\b[A-Z][a-zA-Z0-9.'-]+(?:\s+[A-Z][a-zA-Z0-9.'-]+)+\b")
# A single capitalized word carrying an org suffix is also an entity ("Anthropic Inc", "MIT Lab").
_ORG_SUFFIX = re.compile(
    r"\b[A-Z][a-zA-Z0-9.&'-]+(?:\s+[A-Z][a-zA-Z0-9.&'-]+)*\s+"
    r"(?:Inc|LLC|Ltd|Corp|Co|GmbH|PLC|Foundation|University|Institute|Labs?|Group|Team)\b"
)
# A social-style handle: "@maria", "@acme_co".
_HANDLE = re.compile(r"(?<!\w)@([A-Za-z0-9_]{2,})\b")

# Entities are stable referents, not timestamped captures, so their Original is minted with a fixed
# (empty) `created` — the id then depends only on the name, so the same entity collapses to one node.
_ENTITY_CREATED = ""


@dataclass(frozen=True)
class EntityMention:
    """A person/organization mentioned in a note (its display name, whitespace-normalized)."""

    name: str


class EntityExtractor(Protocol):
    """Propose the entities a piece of text mentions (Strategy)."""

    def extract(self, text: str) -> tuple[EntityMention, ...]: ...


class HeuristicEntityExtractor:
    """Deterministic offline extractor: multi-word proper nouns, org-suffixed names, and @handles.

    Conservative by design (≥2-word proper nouns, explicit org suffixes, handles) to keep noise low
    without understanding the text. Order-stable and de-duplicated case-insensitively.
    """

    def extract(self, text: str) -> tuple[EntityMention, ...]:
        out: list[EntityMention] = []
        seen: set[str] = set()

        def add(name: str) -> None:
            normalized = " ".join(name.split())
            key = normalized.casefold()
            if normalized and key not in seen:
                seen.add(key)
                out.append(EntityMention(name=normalized))

        for match in _HANDLE.finditer(text):
            add("@" + match.group(1))
        for pattern in (_ORG_SUFFIX, _PROPER_NOUN):
            for match in pattern.finditer(text):
                add(match.group(0))
        return tuple(out)


def entity_note(name: str) -> tuple[Original, Note]:
    """The content-addressed Original + `entity` Note for an entity `name` (stable, id by name)."""
    original = Original.capture(name, Source(app="entity"), _ENTITY_CREATED)
    proposed = ProposedNote(original_id=original.id, title=name, body="", type=NoteType.ENTITY)
    return original, Note.from_proposed(proposed)


def materialize_entities(
    repo: NoteRepository,
    originals: OriginalStore,
    embedder: Embedder,
    source_note_id: str,
    mentions: tuple[EntityMention, ...],
) -> tuple[str, ...]:
    """Create an `entity` note per mention and an `involves` edge from the source note to each.

    Append-only & idempotent: a no-op if the source note is unknown; identical entities/edges collapse
    (content-addressed ids + idempotent `add_note`/`add_edge`). Returns the involved entity ids,
    de-duplicated and order-stable, excluding any self-reference.
    """
    if repo.get_note(source_note_id) is None:
        return ()
    entity_ids: list[str] = []
    seen: set[str] = set()
    for mention in mentions:
        original, note = entity_note(mention.name)
        if note.id == source_note_id or note.id in seen:
            continue
        seen.add(note.id)
        originals.add(original)
        repo.add_note(note, embedder.embed(mention.name))
        repo.add_edge(Edge(source_note_id, note.id, EdgeKind.INVOLVES))
        entity_ids.append(note.id)
    return tuple(entity_ids)
