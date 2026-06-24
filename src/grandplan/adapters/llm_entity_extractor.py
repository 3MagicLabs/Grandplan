"""LlmEntityExtractor — LLM-proposed entity extraction (ROADMAP item 3), offline via Ollama.

Drop-in `EntityExtractor` (Strategy): asks a local model for the people and organizations a piece of
text mentions, as JSON. Each name is sanitized (whitespace-normalized, length-bounded) and the result
is **unioned with the deterministic `HeuristicEntityExtractor`** so handles/proper nouns the model
misses are still caught; on any model/parse/transport failure it falls back to the heuristic alone —
so extraction never breaks and stays offline-safe.

The HTTP call is injected (`chat`), so prompt-building / parsing / sanitization / fallback are
unit-tested here; a real Ollama + pulled model integration-tests it on the user's machine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from grandplan.adapters._ollama import loads_lenient
from grandplan.adapters.ollama_organizer import DEFAULT_MODEL
from grandplan.core.entities import EntityExtractor, EntityMention, HeuristicEntityExtractor

logger = logging.getLogger(__name__)

ChatClient = Callable[[str, str], str]

_MAX_NAME_LEN = 80  # a person/org name is short; longer = the model returned a sentence, drop it

_INSTRUCTION = (
    "Extract the PEOPLE and ORGANIZATIONS explicitly mentioned in the text. Return ONLY a JSON "
    'object {"entities": [<name>, ...]} with each name exactly as written (a person, company, team, '
    "or @handle). Do NOT include projects, tasks, dates, places, or generic nouns. Use [] when none "
    "are mentioned — do not invent names."
)


def build_entity_prompt(text: str) -> str:
    return f"{_INSTRUCTION}\n\nTEXT:\n{text}"


def parse_entities(raw: str) -> tuple[EntityMention, ...]:
    """Validate the model's JSON into sanitized, de-duplicated mentions (case-insensitive)."""
    data = loads_lenient(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    items = data.get("entities")
    if not isinstance(items, list):
        return ()
    out: list[EntityMention] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        name = " ".join(item.split())
        key = name.casefold()
        if name and len(name) <= _MAX_NAME_LEN and key not in seen:
            seen.add(key)
            out.append(EntityMention(name=name))
    return tuple(out)


def _ollama_chat(model: str, prompt: str) -> str:  # pragma: no cover - needs a running Ollama
    from grandplan.adapters.llm_placer import _ollama_chat as chat

    return chat(model, prompt)


class LlmEntityExtractor:
    """Entity extractor backed by a local Ollama model, unioned with the heuristic + fallback."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        chat: ChatClient = _ollama_chat,
        fallback: EntityExtractor | None = None,
    ) -> None:
        self._model = model
        self._chat = chat
        self._fallback: EntityExtractor = fallback or HeuristicEntityExtractor()

    def extract(self, text: str) -> tuple[EntityMention, ...]:
        heuristic = self._fallback.extract(text)
        try:
            llm = parse_entities(self._chat(self._model, build_entity_prompt(text)))
        except Exception as exc:  # noqa: BLE001 - bad JSON, model not pulled, or Ollama not running
            logger.warning("entity extraction failed; using heuristic only: %s", exc)
            return heuristic
        return _union(heuristic, llm)


def _union(
    first: tuple[EntityMention, ...], second: tuple[EntityMention, ...]
) -> tuple[EntityMention, ...]:
    """Order-stable union of two mention tuples, de-duplicated case-insensitively (first wins)."""
    out: list[EntityMention] = []
    seen: set[str] = set()
    for mention in (*first, *second):
        key = mention.name.casefold()
        if key not in seen:
            seen.add(key)
            out.append(mention)
    return tuple(out)
