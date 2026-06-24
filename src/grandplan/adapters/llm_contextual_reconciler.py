"""LlmContextualReconciler — neighborhood-aware reconciliation (US-10 / RAG), offline via Ollama.

The pairwise `LlmRelationshipClassifier` judges the new note against ONE candidate at a time, blind
to the rest of the graph. This `Reconciler` instead gives the local model the new note plus the
WHOLE set of most-similar existing notes at once — each with its title, type, **derived status**, and
a body snippet — and asks, in a single call, how the new note relates to each (`duplicate` /
`supersedes` / `refines` / `builds_on` / `contradicts` / `related`). So the model reasons about how
the capture fits the existing knowledge holistically, not in isolation.

The resulting relationships drive the same typed edges as before (ADR-0007): `supersedes` makes the
old note stale in the plan, `contradicts` flags a needs-review, `duplicate` routes to the merge path
— so a richer assessment automatically propagates through the graph. Append-only and human-approved
(the review dialog still gates every change). Falls back to the deterministic `SimilarityReconciler`
on any model/parse/transport failure; offline (localhost Ollama only). The chat call is injected, so
prompt/parse/validation/fallback are unit-tested here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from grandplan.adapters._ollama import chat_json, loads_lenient
from grandplan.adapters.ollama_organizer import DEFAULT_MODEL, OLLAMA_TIMEOUT_S
from grandplan.core.models import NoteStatus, ProposedNote
from grandplan.core.ports import NoteRepository
from grandplan.core.reconcile import (
    RelatedCandidate,
    Relationship,
    ReconcileProposal,
    Reconciler,
    SimilarityReconciler,
)

logger = logging.getLogger(__name__)

ChatClient = Callable[[str, str], str]
_VALID = {relationship.value: relationship for relationship in Relationship}
# Status changes the new note may imply for an EXISTING related note (Slice B). `inbox` excluded —
# it's the default, not a meaningful change. The user approves every change in the review dialog.
_STATUS_CHANGES = {
    status.value: status
    for status in (
        NoteStatus.DONE,
        NoteStatus.ACTIVE,
        NoteStatus.NEXT,
        NoteStatus.SUPERSEDED,
        NoteStatus.NEEDS_REVIEW,
    )
}
_BODY_SNIPPET = 280  # cap each candidate's body in the prompt (CPU-friendly, bounded context)

_INSTRUCTION = (
    "You decide how a NEW note relates to each EXISTING note in the user's knowledge graph, and "
    "whether the new note implies a STATUS change to any existing note. You are given the new note "
    "and a numbered list of the most-similar existing notes (with their current status). Return "
    'ONLY a JSON object {"relationships": [{"id": "<existing id>", "relationship": <one of: '
    + ", ".join(_VALID)
    + '>, "status_change": <one of: '
    + ", ".join(_STATUS_CHANGES)
    + ", or null>}]}. relationship: 'duplicate' if same thing; 'supersedes' if the new note "
    "replaces/obsoletes it; 'refines' if it sharpens/corrects it; 'builds_on' if it extends it; "
    "'contradicts' if they genuinely conflict; otherwise 'related'. status_change: set it ONLY when "
    "the new note clearly implies the existing note's status should change (e.g. 'done' if the new "
    "note completes it, 'superseded' if it obsoletes it, 'needs-review' if it conflicts) — otherwise "
    "null. Use only ids from the list; omit a note rather than guess."
)


def build_reconcile_prompt(
    new: ProposedNote, candidates: list[tuple[str, str, str, str, str]]
) -> str:
    """`candidates` = (id, title, type, status, body) for each most-similar existing note."""
    lines = [
        f"NEW NOTE: title={new.title!r} type={new.type.value}",
        new.body[:_BODY_SNIPPET],
        "",
        "EXISTING NOTES:",
    ]
    for cid, title, ctype, status, body in candidates:
        lines.append(f"- id={cid} type={ctype} status={status} title={title!r}")
        snippet = " ".join(body.split())[:_BODY_SNIPPET]
        if snippet:
            lines.append(f"    {snippet}")
    return f"{_INSTRUCTION}\n\n" + "\n".join(lines)


def parse_relationships(raw: str, valid_ids: set[str]) -> dict[str, Relationship]:
    """Map the model's JSON to {existing id -> Relationship}, dropping unknown ids/relationships."""
    data = loads_lenient(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    items = data.get("relationships", [])
    if not isinstance(items, list):
        raise ValueError('"relationships" must be a list')
    out: dict[str, Relationship] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id", "")).strip()
        rel = _VALID.get(str(item.get("relationship", "")).strip().lower())
        if cid in valid_ids and rel is not None:
            out[cid] = rel
    return out


def parse_status_changes(raw: str, valid_ids: set[str]) -> dict[str, NoteStatus]:
    """Map the model's per-existing-note `status_change` to {id -> NoteStatus} (Slice B), dropping
    unknown ids / statuses / nulls."""
    data = loads_lenient(raw)
    items = data.get("relationships", []) if isinstance(data, dict) else []
    out: dict[str, NoteStatus] = {}
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id", "")).strip()
            status = _STATUS_CHANGES.get(str(item.get("status_change", "")).strip().lower())
            if cid in valid_ids and status is not None:
                out[cid] = status
    return out


def _ollama_chat(model: str, prompt: str) -> str:  # pragma: no cover - needs a running Ollama
    return chat_json(model, prompt, timeout=OLLAMA_TIMEOUT_S)


class LlmContextualReconciler:
    """A Reconciler that classifies the new note against the whole neighborhood in one LLM call."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        chat: ChatClient = _ollama_chat,
        fallback: Reconciler | None = None,
        link_threshold: float = 0.30,
        limit: int = 5,
    ) -> None:
        self._model = model
        self._chat = chat
        self._fallback: Reconciler = fallback or SimilarityReconciler(
            link_threshold=link_threshold, limit=limit
        )
        self._link = link_threshold
        self._limit = limit

    def reconcile(
        self, proposed: ProposedNote, embedding: tuple[float, ...], repo: NoteRepository
    ) -> ReconcileProposal:
        ranked = repo.most_similar(embedding, limit=self._limit, threshold=self._link)
        if not ranked:
            return ReconcileProposal(())  # nothing related yet → nothing to classify
        candidates = [
            (
                note.id,
                note.title,
                note.type.value,
                (repo.status_of(note.id) or note.status).value,
                note.body,
            )
            for note, _ in ranked
        ]
        valid_ids = {cid for cid, *_ in candidates}
        try:
            raw = self._chat(self._model, build_reconcile_prompt(proposed, candidates))
            relationships = parse_relationships(raw, valid_ids)
            status_changes = parse_status_changes(raw, valid_ids)  # Slice B
        except Exception as exc:  # noqa: BLE001 - bad JSON, model not pulled, or Ollama not running
            logger.warning("contextual reconcile failed; using similarity fallback: %s", exc)
            return self._fallback.reconcile(proposed, embedding, repo)
        return ReconcileProposal(
            tuple(
                RelatedCandidate(
                    note=note,
                    score=score,
                    relationship=relationships.get(note.id, Relationship.RELATED),
                    suggested_status=status_changes.get(note.id),
                )
                for note, score in ranked
            )
        )
