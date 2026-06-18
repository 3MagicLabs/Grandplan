"""Artifact-attach flow — "here's the doc for note X → update my vault" (PR-E of ADR-0008).

Given a real artifact (a file path or URL), find the existing note it fulfils by embedding
similarity and **attach it as a `resource` event** (append-only; the note is never mutated). The
attachment shows up in the note's `## Resources` section and in its history / the "what moved"
digest — so attaching is itself recorded progress. Single best match only; propagation to related
notes is a deferred enhancement.
"""

from __future__ import annotations

from dataclasses import dataclass

from grandplan.core.models import Note
from grandplan.core.ports import Embedder, NoteRepository
from grandplan.core.resources import Resource, classify_reference, describe_reference

# A reference is matched on sparse text (a filename), so the bar is the reconciler's link threshold
# (0.30), not the stricter update/edit-match bar — the user explicitly asked to attach this ref.
_DEFAULT_MATCH_THRESHOLD = 0.30


@dataclass(frozen=True)
class AttachResult:
    """The note an artifact was attached to, and the resource that was recorded."""

    note: Note
    resource: Resource


def attach(
    ref: str,
    *,
    repo: NoteRepository,
    embedder: Embedder,
    description: str | None = None,
    label: str = "",
    match_threshold: float = _DEFAULT_MATCH_THRESHOLD,
) -> AttachResult | None:
    """Attach `ref` to the single best-matching note (or None if nothing matches confidently).

    `description` overrides the text used for matching (default: words derived from the ref); `label`
    is an optional display label for the rendered resource.
    """
    resource = classify_reference(ref, label=label)
    query = (description or "").strip() or describe_reference(ref)
    if not query:
        return None
    matches = repo.most_similar(embedder.embed(query), limit=1, threshold=match_threshold)
    if not matches:
        return None
    note, _score = matches[0]
    repo.add_resource(note.id, resource)
    return AttachResult(note=note, resource=resource)
