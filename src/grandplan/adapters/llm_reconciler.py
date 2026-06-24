"""LlmRelationshipClassifier — LLM-proposed relationship classification (US-10), offline via Ollama.

Drop-in `RelationshipClassifier` (Strategy, ADR-0007): asks a local model how a NEW note relates to
an EXISTING candidate — `duplicate` / `supersedes` / `refines` / `builds_on` / `contradicts` /
`related` — as JSON, validates it against the `Relationship` enum, and **falls back to the
deterministic `SimilarityClassifier`** on any model/parse/transport failure, so the pipeline never
breaks and stays offline-safe.

The HTTP call is injected (`chat`), so prompt-building / parsing / validation / fallback are
unit-tested here; running a real Ollama + pulled model integration-tests it on Windows.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from grandplan.adapters._ollama import chat_json, loads_lenient
from grandplan.adapters.ollama_organizer import DEFAULT_MODEL, OLLAMA_TIMEOUT_S
from grandplan.core.models import Note, ProposedNote
from grandplan.core.reconcile import Relationship, RelationshipClassifier, SimilarityClassifier

logger = logging.getLogger(__name__)

ChatClient = Callable[[str, str], str]
_VALID = {relationship.value: relationship for relationship in Relationship}

_INSTRUCTION = (
    "You classify how a NEW note relates to one EXISTING note. "
    'Return ONLY a JSON object {"relationship": <one of: ' + ", ".join(_VALID) + ">}. "
    "Choose 'duplicate' if they state the same thing; 'supersedes' if the new replaces/obsoletes "
    "the old; 'refines' if it sharpens or corrects the old; 'builds_on' if it extends it; "
    "'contradicts' if they genuinely conflict; otherwise 'related'."
)


def build_classify_prompt(new: ProposedNote, candidate: Note) -> str:
    return (
        f"{_INSTRUCTION}\n\nEXISTING NOTE:\n{candidate.title}\n{candidate.body}"
        f"\n\nNEW NOTE:\n{new.title}\n{new.body}"
    )


def parse_relationship(raw: str) -> Relationship:
    data = loads_lenient(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    key = str(data.get("relationship", "")).strip().lower()
    if key not in _VALID:
        raise ValueError(f"unknown relationship: {key!r}")
    return _VALID[key]


def _ollama_chat(model: str, prompt: str) -> str:  # pragma: no cover - needs a running Ollama
    return chat_json(model, prompt, timeout=OLLAMA_TIMEOUT_S)


class LlmRelationshipClassifier:
    """RelationshipClassifier backed by a local Ollama model, with a deterministic fallback."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        chat: ChatClient = _ollama_chat,
        fallback: RelationshipClassifier | None = None,
    ) -> None:
        self._model = model
        self._chat = chat
        self._fallback: RelationshipClassifier = fallback or SimilarityClassifier()

    def classify(self, new: ProposedNote, candidate: Note, score: float) -> Relationship:
        try:
            return parse_relationship(
                self._chat(self._model, build_classify_prompt(new, candidate))
            )
        except Exception as exc:  # noqa: BLE001 - bad JSON, model not pulled, or Ollama not running
            logger.warning("relationship classify failed; using similarity fallback: %s", exc)
            return self._fallback.classify(new, candidate, score)
