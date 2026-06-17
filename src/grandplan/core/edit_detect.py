"""EditDetector — detect *field-edit intent* in a capture (PR-C of ADR-0008).

A capture is sometimes neither a new idea nor a status change but a **detail edit** to an existing
note: "launch slipped to Q3" (a due change), "rename the resume task to CV" (a retitle). The detector
maps such a capture to a `NoteEdit`; everything else returns `None`.

A **Strategy** behind a port (ADR-0003/0007), mirroring `UpdateDetector`: the deterministic, offline
`HeuristicEditDetector` extracts the two edits that are tractable without an LLM — **due** and
**retitle** — and is the baseline (and the LLM detector's fallback). The richer `LlmEditDetector`
(`adapters.llm_edit_detector`) also proposes body/tag edits. The detector only *classifies*; matching
the note, proposing the edit, and human approval all happen downstream (`app.review`).
"""

from __future__ import annotations

import re
from typing import Protocol

from grandplan.core.models import NoteEdit

_MAX_VALUE = 120  # cap an extracted value so a runaway capture can't bloat a field

# "rename … to <X>" / "retitle … to <X>". The lazy `.*?` stops at the FIRST " to " after the
# keyword, so the new title keeps everything after it — a title that itself contains "to" (e.g.
# "rename it to back to basics" → "back to basics") is preserved whole rather than truncated.
_RETITLE = re.compile(r"\b(?:rename|retitle)\b.*?\bto\s+(?P<title>.+?)\s*$", re.IGNORECASE)
# "call it <X>" — a second, common retitle phrasing.
_CALL_IT = re.compile(r"\bcall it\s+(?P<title>.+?)\s*$", re.IGNORECASE)
# A due/deadline change: an explicit "due"/"deadline", or a deadline-specific "slipped/pushed/bumped/
# rescheduled to <X>" phrase (the vaguer "moved to" is excluded — too often non-date English). An
# optional leading preposition ("due at/on/by <X>") is consumed so it doesn't pollute the value.
_DUE = re.compile(
    r"\b(?:due(?:\s*date)?|deadline|(?:slipped|pushed|bumped|rescheduled?)\s+to)\b"
    r"[:\s]+(?:(?:at|on|by)\s+)?(?P<due>.+?)\s*$",
    re.IGNORECASE,
)


class EditDetector(Protocol):
    """Classify whether a capture expresses a field edit, and which fields change (Strategy)."""

    def detect(self, text: str) -> NoteEdit | None: ...


class HeuristicEditDetector:
    """Deterministic, offline baseline: extract a due or retitle edit from a capture (or None)."""

    def detect(self, text: str) -> NoteEdit | None:
        for pattern in (_RETITLE, _CALL_IT):  # a clear retitle wins over a trailing date-ish word
            match = pattern.search(text)
            if match:
                title = _clean(match.group("title"))
                if title:
                    return NoteEdit(title=title)
        match = _DUE.search(text)
        if match:
            due = _clean(match.group("due"))
            if due:
                return NoteEdit(due=due)
        return None


def _clean(value: str) -> str:
    """Normalise an extracted field value: trim whitespace, surrounding quotes, a trailing period."""
    return value.strip().strip("\"'").strip().rstrip(".").strip()[:_MAX_VALUE]
