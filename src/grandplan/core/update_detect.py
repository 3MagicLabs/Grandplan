"""UpdateDetector — detect *progress-update intent* in a capture (PR-B of ADR-0008).

A capture is sometimes not a new idea but an **update** to an existing one ("done: built the
resume", "started the landing page", "up next: the research", "reopen that task"). The detector maps
such a capture to the target `NoteStatus`; everything else (a genuinely new note) returns `None`.

This is a **Strategy** behind a port (ADR-0003/0007), mirroring the Organizer/RelationshipClassifier:
the deterministic, offline `HeuristicUpdateDetector` is the baseline (and the LLM detector's
fallback); an Ollama-backed `LlmUpdateDetector` (`adapters.llm_update_detector`) can drop in behind
the same interface. The detector only *classifies intent*; matching the relevant note, proposing the
change, and requiring human approval all happen downstream (`app.review`), so nothing is auto-applied.
"""

from __future__ import annotations

import re
from typing import Protocol

from grandplan.core.models import NoteStatus

# Canonical intent → target status map. Shared with the LLM parser so both detectors speak the same
# vocabulary. Only maps to existing statuses; `reopen` brings a finished task back to ACTIVE (and so
# back into the actionable plan). NEEDS_REVIEW / SUPERSEDED are intentionally unreachable here — they
# are derived from contradiction/supersede edges, never set directly by a free-text update.
UPDATE_STATUS: dict[str, NoteStatus] = {
    "done": NoteStatus.DONE,
    "active": NoteStatus.ACTIVE,
    "next": NoteStatus.NEXT,
    "reopen": NoteStatus.ACTIVE,
}

# Ordered cue rules (first match wins). `reopen` is checked BEFORE `done` so "not done"/"no longer
# done" is read as a reopen, never as completion.
_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("reopen", ("reopen", "re-open", "not done", "not finished", "no longer done")),
    ("done", ("done", "finished", "completed", "shipped", "wrapped up", "✅", "[x]")),
    (
        "active",
        (
            "started",
            "starting",
            "began",
            "in progress",
            "in-progress",
            "working on",
            "underway",
            "kicked off",
        ),
    ),
    ("next", ("up next", "next up", "do next", "queued", "queue", "on deck")),
)


def _compile(cues: tuple[str, ...]) -> re.Pattern[str]:
    """A pattern matching any cue not flanked by word characters.

    The non-word-boundary lookarounds keep "started" from firing inside "restarted" and "queue"
    from firing inside "dequeued", while still matching symbol cues ("✅", "[x]") that no `\\b`
    boundary would (they aren't word characters).
    """
    alternation = "|".join(re.escape(cue) for cue in cues)
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)")


# Each rule pairs its target status with a compiled cue pattern, in priority order.
_RULES: tuple[tuple[NoteStatus, re.Pattern[str]], ...] = tuple(
    (UPDATE_STATUS[intent], _compile(cues)) for intent, cues in _CUES
)


class UpdateDetector(Protocol):
    """Classify whether a capture expresses update-intent, and toward which status (Strategy)."""

    def detect(self, text: str) -> NoteStatus | None: ...


class HeuristicUpdateDetector:
    """Deterministic, offline baseline: ordered cue matching → a target status (or None)."""

    def detect(self, text: str) -> NoteStatus | None:
        lowered = text.lower()
        for status, pattern in _RULES:
            if pattern.search(lowered):
                return status
        return None
