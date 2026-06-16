"""HeuristicOrganizer — a deterministic, offline baseline Organizer.

Derives a title, cleaned body, type, and tags from captured text without any LLM. A
local-LLM organizer can later replace it behind the `Organizer` port; the Original always
stays verbatim (the organized body is derived, never a substitute for the original).
"""

from __future__ import annotations

import re

from grandplan.core.models import Horizon, NoteType, Original, ProposedNote

_WORD = re.compile(r"[0-9a-z']+")
_MAX_TITLE = 80
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "are",
        "was",
        "you",
        "your",
        "from",
        "have",
        "has",
        "will",
        "would",
        "should",
        "could",
        "but",
        "not",
        "all",
        "any",
        "can",
        "out",
        "get",
        "got",
        "into",
        "about",
        "they",
        "them",
        "their",
        "there",
    }
)
# (type, substring hints) — first match wins; otherwise IDEA.
_TYPE_HINTS: tuple[tuple[NoteType, tuple[str, ...]], ...] = (
    (NoteType.QUESTION, ("?", "how do", "should i", "what if")),
    (NoteType.TASK, ("todo", "to-do", "task", "deadline", " due ", "finish", "submit")),
    (NoteType.GOAL, ("goal", "objective", "vision", "aim to")),
    (NoteType.PROJECT, ("project", "milestone", "launch", "roadmap")),
    (NoteType.DECISION, ("decide", "decision", "choose", "trade-off")),
)


class HeuristicOrganizer:
    """A no-LLM baseline that proposes a structured note from a captured Original."""

    def organize(self, original: Original) -> ProposedNote:
        text = original.text
        return ProposedNote(
            original_id=original.id,
            title=_title(text),
            body=text.strip(),
            type=_infer_type(text),
            tags=_keywords(text),
            horizon=Horizon.ACTION,
        )


def _title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:_MAX_TITLE]
    return "Untitled note"


def _infer_type(text: str) -> NoteType:
    lowered = text.lower()
    for note_type, hints in _TYPE_HINTS:
        if any(hint in lowered for hint in hints):
            return note_type
    return NoteType.IDEA


def _keywords(text: str, limit: int = 5) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for word in _WORD.findall(text.lower()):
        if len(word) < 3 or word in _STOPWORDS:
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts, key=lambda word: (-counts[word], word))
    return tuple(ranked[:limit])
