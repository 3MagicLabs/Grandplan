"""Organize-quality checks (QAS-8) — measure note quality so 'good output' is never assumed.

These detect the fingerprints of *un-organized* output (the heuristic fallback, or a model that
barely did anything): a title that is just the verbatim first line of the capture, a body identical
to the original, or no topical tags. The run report and the `doctor` command surface these so a test
run tells the user *what went wrong* (e.g. "every note is low-quality → the LLM never ran"). Pure,
offline, deterministic.
"""

from __future__ import annotations

from grandplan.core.models import Note, Original

# Mirrors the organizers' title cap (organize.py / ollama_organizer.py): a title equal to the
# original's first line truncated to this length is the heuristic-fallback signature.
_TITLE_CAP = 80


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def note_quality_issues(note: Note, original: Original) -> tuple[str, ...]:
    """Human-readable quality problems with a note relative to its Original (empty = looks good)."""
    issues: list[str] = []
    title = note.title.strip()
    first_line = _first_line(original.text)
    # 1. Title is just the raw capture's first line (optionally truncated) — not a real title.
    if title and (title == first_line[:_TITLE_CAP] or title == first_line):
        issues.append("title is the raw capture text, not a concise summary")
    # 2. Title was cut off mid-word at the cap (a truncation artefact, never an intentional title).
    if len(title) >= _TITLE_CAP and title[-1].isalnum():
        issues.append("title is truncated mid-word")
    # 3. Body is the verbatim original — the note was never actually organized.
    if note.body.strip() == original.text.strip():
        issues.append("body is the unmodified capture (not organized)")
    # 4. No topical tags — nothing to group or colour by beyond the structural tags.
    if not note.tags:
        issues.append("no topical tags")
    return tuple(issues)


def is_low_quality(note: Note, original: Original) -> bool:
    """True if the note shows any un-organized fingerprint (drives the report's low-quality count)."""
    return bool(note_quality_issues(note, original))
