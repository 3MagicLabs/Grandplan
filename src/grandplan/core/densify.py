"""Offline mention -> wikilink densification (pure).

Surfaces likely links grandplan's embedder might miss: when a note's body literally names another
note's title (whole-word, case-insensitive), that's almost certainly a relationship worth recording.
Pure and deterministic, no model call (adopts the automatic-linker pattern from docs/research, area B).
Suggestion only — the caller decides whether to record a RELATES edge (preserving the human/agent
approval gate); this never mutates a note.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from grandplan.core.models import Note


def suggest_mention_links(
    note: Note, others: Iterable[Note], *, min_chars: int = 3
) -> tuple[Note, ...]:
    """Notes from `others` whose title appears as a whole-word phrase in `note.body`.

    Case-insensitive, whole-word (so "cat" does not match inside "category"), self excluded, titles
    shorter than `min_chars` skipped as noise, each target returned at most once in `others` order.
    """
    body = note.body
    suggestions: list[Note] = []
    seen: set[str] = set()
    for other in others:
        if other.id == note.id or other.id in seen:
            continue
        title = other.title.strip()
        if len(title) < min_chars:
            continue
        if re.search(rf"\b{re.escape(title)}\b", body, flags=re.IGNORECASE):
            suggestions.append(other)
            seen.add(other.id)
    return tuple(suggestions)
