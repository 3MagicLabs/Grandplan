"""LlmPlacer — LLM-proposed structural placement (PR-G), offline via Ollama.

Drop-in `Placer` (Strategy): given a new note and a bounded list of the most-similar existing notes,
asks a local model which one the note is **part of** (its parent) and which ones it **depends on**
(prerequisites), as JSON. Every returned id is validated against the candidate set (a hallucinated
id is dropped), and on any model/parse/transport failure it **falls back to the deterministic
`HeuristicPlacer`** — so the pipeline never breaks and stays offline-safe.

The HTTP call is injected (`chat`), so prompt-building / parsing / validation / fallback are
unit-tested here; a real Ollama + pulled model integration-tests it on the user's machine.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from grandplan.adapters.ollama_organizer import DEFAULT_MODEL
from grandplan.core.models import ProposedNote
from grandplan.core.placement import (
    _DEFAULT_CANDIDATES,
    HeuristicPlacer,
    Placement,
    Placer,
)
from grandplan.core.ports import NoteRepository

logger = logging.getLogger(__name__)

ChatClient = Callable[[str, str], str]

_INSTRUCTION = (
    "You decide how a NEW note fits into an existing knowledge graph. You are given the new note and "
    "a numbered list of candidate existing notes. Return ONLY a JSON object "
    '{"parent": <candidate id the new note is PART OF, or null>, '
    '"depends_on": [<candidate ids that must be DONE FIRST>], '
    '"blocks": [<candidate ids this new note holds up / must be done before>], '
    '"waiting_on": [<candidate ids this note is externally waiting on>]}. '
    "A parent is a broader goal/project the note belongs under. depends_on = prerequisites. "
    "blocks = notes that cannot proceed until this one is done. waiting_on = something external this "
    "note awaits. Use only ids from the candidate list; use null / [] when none truly apply — do not "
    "force a link."
)


def build_placement_prompt(
    proposed: ProposedNote, candidates: list[tuple[str, str, str, str]]
) -> str:
    """`candidates` = (id, title, type, horizon) tuples, most-similar first."""
    lines = [
        f"NEW NOTE: title={proposed.title!r} type={proposed.type.value} horizon={proposed.horizon.value}",
        "",
        "CANDIDATES:",
    ]
    lines += [
        f"- id={cid} title={title!r} type={ctype} horizon={horizon}"
        for cid, title, ctype, horizon in candidates
    ]
    return f"{_INSTRUCTION}\n\n" + "\n".join(lines)


def parse_placement(raw: str, valid_ids: set[str]) -> Placement:
    """Validate the model's JSON against the candidate ids (drops hallucinated / self ids)."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    parent_raw = data.get("parent")
    parent = str(parent_raw).strip() if parent_raw not in (None, "") else None
    if parent is not None and parent not in valid_ids:
        parent = None  # a hallucinated parent is no parent
    # Each target gets at most ONE structural relation; the parent is excluded from all of them and
    # the relations don't overlap (first-listed wins), so the recorded edges are unambiguous.
    claimed: set[str] = {parent} if parent is not None else set()
    depends_on = _valid_ids(data.get("depends_on"), valid_ids, claimed)
    blocks = _valid_ids(data.get("blocks"), valid_ids, claimed)
    waiting_on = _valid_ids(data.get("waiting_on"), valid_ids, claimed)
    return Placement(parent_id=parent, depends_on=depends_on, blocks=blocks, waiting_on=waiting_on)


def _valid_ids(raw: object, valid_ids: set[str], claimed: set[str]) -> tuple[str, ...]:
    """The ids in `raw` that are real candidates and not already claimed (parent / another relation)."""
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for item in raw:
        candidate = str(item).strip()
        if candidate in valid_ids and candidate not in claimed:
            out.append(candidate)
            claimed.add(candidate)
    return tuple(out)


def _ollama_chat(model: str, prompt: str) -> str:  # pragma: no cover - needs a running Ollama
    try:
        import ollama
    except ImportError as exc:
        raise RuntimeError("ollama not installed; `pip install grandplan[llm]`") from exc
    response = ollama.chat(
        model=model, messages=[{"role": "user", "content": prompt}], format="json"
    )
    return str(response["message"]["content"])


class LlmPlacer:
    """Placer backed by a local Ollama model, with a deterministic heuristic fallback."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        chat: ChatClient = _ollama_chat,
        fallback: Placer | None = None,
        candidates: int = _DEFAULT_CANDIDATES,
    ) -> None:
        self._model = model
        self._chat = chat
        self._fallback: Placer = fallback or HeuristicPlacer(candidates=candidates)
        self._candidates = candidates

    def place(
        self, proposed: ProposedNote, embedding: tuple[float, ...], repo: NoteRepository
    ) -> Placement:
        ranked = repo.most_similar(embedding, limit=self._candidates, threshold=0.0)
        if not ranked:  # nothing to attach to yet
            return Placement()
        candidates = [
            (note.id, note.title, note.type.value, note.horizon.value) for note, _ in ranked
        ]
        valid_ids = {cid for cid, *_ in candidates}
        try:
            return parse_placement(
                self._chat(self._model, build_placement_prompt(proposed, candidates)), valid_ids
            )
        except Exception as exc:  # noqa: BLE001 - bad JSON, model not pulled, or Ollama not running
            logger.warning("placement failed; using heuristic fallback: %s", exc)
            return self._fallback.place(proposed, embedding, repo)
