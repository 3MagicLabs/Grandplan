"""LlmUpdateDetector — LLM-proposed update-intent detection (PR-B, ADR-0008), offline via Ollama.

Drop-in `UpdateDetector` (Strategy): asks a local model whether a capture is a *progress update* to
an existing idea and toward which status — `done` / `active` / `next` / `reopen` / `none` — as JSON,
validates it against the shared `UPDATE_STATUS` vocabulary, and **falls back to the deterministic
`HeuristicUpdateDetector`** on any model/parse/transport failure, so the pipeline never breaks and
stays offline-safe. A successful `"none"` is authoritative (a real "this is a new note" decision),
not a failure — the fallback runs only on errors.

The HTTP call is injected (`chat`), so prompt-building / parsing / validation / fallback are
unit-tested here; running a real Ollama + pulled model integration-tests it on the user's machine.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from grandplan.adapters.ollama_organizer import DEFAULT_MODEL, OLLAMA_TIMEOUT_S
from grandplan.core.models import NoteStatus
from grandplan.core.update_detect import UPDATE_STATUS, HeuristicUpdateDetector, UpdateDetector

logger = logging.getLogger(__name__)

ChatClient = Callable[[str, str], str]
# The valid replies: every update intent plus the explicit "this is a new note" verdict.
_INTENTS = (*UPDATE_STATUS.keys(), "none")

_INSTRUCTION = (
    "You decide whether a captured note is a PROGRESS UPDATE to an existing task/idea, and toward "
    'which state. Return ONLY a JSON object {"update": <one of: ' + ", ".join(_INTENTS) + ">}. "
    "Use 'done' if it reports completion; 'active' if work has started / is in progress; 'next' if "
    "it should be queued up next; 'reopen' if a finished item is no longer done; otherwise 'none' "
    "(it is a brand-new note, not an update)."
)


def build_update_prompt(text: str) -> str:
    return f"{_INSTRUCTION}\n\nCAPTURE:\n{text}"


def parse_update(raw: str) -> NoteStatus | None:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    value = data.get("update")
    if value is None:  # missing key or JSON null → the model didn't answer; trigger the fallback
        raise ValueError('missing "update" key')
    key = str(value).strip().lower()
    if key == "none":  # an explicit, authoritative "this is a new note, not an update"
        return None
    if key not in UPDATE_STATUS:
        raise ValueError(f"unknown update intent: {key!r}")
    return UPDATE_STATUS[key]


def _ollama_chat(model: str, prompt: str) -> str:  # pragma: no cover - needs a running Ollama
    try:
        import ollama
    except ImportError as exc:
        raise RuntimeError("ollama not installed; `pip install grandplan[llm]`") from exc
    response = ollama.Client(timeout=OLLAMA_TIMEOUT_S).chat(
        model=model, messages=[{"role": "user", "content": prompt}], format="json"
    )
    return str(response["message"]["content"])


class LlmUpdateDetector:
    """UpdateDetector backed by a local Ollama model, with a deterministic heuristic fallback."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        chat: ChatClient = _ollama_chat,
        fallback: UpdateDetector | None = None,
    ) -> None:
        self._model = model
        self._chat = chat
        self._fallback: UpdateDetector = fallback or HeuristicUpdateDetector()

    def detect(self, text: str) -> NoteStatus | None:
        try:
            return parse_update(self._chat(self._model, build_update_prompt(text)))
        except Exception as exc:  # noqa: BLE001 - bad JSON, model not pulled, or Ollama not running
            logger.warning("update-intent detect failed; using heuristic fallback: %s", exc)
            return self._fallback.detect(text)
