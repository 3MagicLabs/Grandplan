"""LlmEditDetector — LLM-proposed field-edit detection (PR-C, ADR-0008), offline via Ollama.

Drop-in `EditDetector` (Strategy): asks a local model whether a capture is a detail **edit** to an
existing note and which fields change — `title` / `body` / `tags` / `due` — as JSON, validates it,
and **falls back to the deterministic `HeuristicEditDetector`** on any model/parse/transport failure,
so the pipeline never breaks and stays offline-safe. A successful `null` (or an empty edit) is an
authoritative "no edit", not a failure — the fallback runs only on errors.

The HTTP call is injected (`chat`), so prompt-building / parsing / validation / fallback are
unit-tested here; running a real Ollama + pulled model integration-tests it on the user's machine.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from grandplan.adapters.ollama_organizer import DEFAULT_MODEL, OLLAMA_TIMEOUT_S
from grandplan.core.edit_detect import EditDetector, HeuristicEditDetector
from grandplan.core.models import NoteEdit

logger = logging.getLogger(__name__)

ChatClient = Callable[[str, str], str]

_INSTRUCTION = (
    "You decide whether a captured note is a DETAIL EDIT to an existing task/idea, and which fields "
    'change. Return ONLY a JSON object {"edit": <object or null>}. The edit object may set any of: '
    '"title" (string), "body" (string), "tags" (array of strings), "due" (string). Include ONLY the '
    "fields that change; omit the rest. Use null (no edit object) when the capture is a brand-new "
    "note or a status change rather than an edit to an existing one."
)


def build_edit_prompt(text: str) -> str:
    return f"{_INSTRUCTION}\n\nCAPTURE:\n{text}"


def parse_edit(raw: str) -> NoteEdit | None:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    if "edit" not in data:
        raise ValueError('missing "edit" key')
    edit = data["edit"]
    if edit is None:  # authoritative "this is not an edit"
        return None
    if not isinstance(edit, dict):
        raise ValueError('"edit" must be an object or null')
    note_edit = NoteEdit(
        title=_opt_str(edit.get("title")),
        body=_opt_str(edit.get("body")),
        tags=_opt_tags(edit.get("tags")),
        due=_opt_str(edit.get("due")),
    )
    return None if note_edit.is_empty() else note_edit


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_tags(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    tags = tuple(str(tag).strip() for tag in value if str(tag).strip())
    return tags or None


def _ollama_chat(model: str, prompt: str) -> str:  # pragma: no cover - needs a running Ollama
    try:
        import ollama
    except ImportError as exc:
        raise RuntimeError(
            f"ollama client unavailable ({exc}); `pip install grandplan[llm]`"
        ) from exc
    response = ollama.Client(timeout=OLLAMA_TIMEOUT_S).chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={"temperature": 0},
        keep_alive="30m",
    )
    return str(response["message"]["content"])


class LlmEditDetector:
    """EditDetector backed by a local Ollama model, with a deterministic heuristic fallback."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        chat: ChatClient = _ollama_chat,
        fallback: EditDetector | None = None,
    ) -> None:
        self._model = model
        self._chat = chat
        self._fallback: EditDetector = fallback or HeuristicEditDetector()

    def detect(self, text: str) -> NoteEdit | None:
        try:
            return parse_edit(self._chat(self._model, build_edit_prompt(text)))
        except Exception as exc:  # noqa: BLE001 - bad JSON, model not pulled, or Ollama not running
            logger.warning("edit detect failed; using heuristic fallback: %s", exc)
            return self._fallback.detect(text)
