"""OllamaOrganizer — a local-LLM Organizer adapter (offline, via Ollama).

Drop-in for the `Organizer` port: asks a local model (Ollama on localhost:11434) for a note's
**title, type, and tags** as JSON, then validates and maps them. The captured original is
**never rewritten** by the model — the note body stays the verbatim-stripped original; the
model only proposes metadata (correctness-first). On any model/parse failure it falls back to
the HeuristicOrganizer so the pipeline never breaks.

The HTTP call is injected (`chat`), so parsing/validation/fallback are unit-tested here; running
a real Ollama + pulled model integration-tests it on the user's machine (`pip install grandplan[llm]`).
"""

from __future__ import annotations

import json
from collections.abc import Callable

from grandplan.core.models import NoteType, Original, ProposedNote
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.ports import Organizer

ChatClient = Callable[[str, str], str]
_DEFAULT_MODEL = "llama3.2:3b"
_MAX_TITLE = 80
_VALID_TYPES = {note_type.value: note_type for note_type in NoteType}


def build_prompt(text: str) -> str:
    return (
        'You organize a captured note. Return ONLY JSON with keys "title" (short string), '
        '"type" (one of: ' + ", ".join(_VALID_TYPES) + '), and "tags" (array of short strings). '
        "Do not rewrite or echo the note body.\n\nNOTE:\n" + text
    )


def parse_proposed(raw: str, original: Original) -> ProposedNote:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    title = (str(data.get("title") or "").strip() or _first_line(original.text))[:_MAX_TITLE]
    note_type = _VALID_TYPES.get(str(data.get("type", "")).strip().lower(), NoteType.IDEA)
    tags_raw = data.get("tags", [])
    tags = (
        tuple(str(tag).strip() for tag in tags_raw if str(tag).strip())
        if isinstance(tags_raw, list)
        else ()
    )
    return ProposedNote(
        original_id=original.id,
        title=title,
        body=original.text.strip(),
        type=note_type,
        tags=tags,
    )


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return "Untitled note"


def _ollama_chat(model: str, prompt: str) -> str:  # pragma: no cover - needs a running Ollama
    try:
        import ollama
    except ImportError as exc:
        raise RuntimeError("ollama not installed; `pip install grandplan[llm]`") from exc
    response = ollama.chat(
        model=model, messages=[{"role": "user", "content": prompt}], format="json"
    )
    return str(response["message"]["content"])


class OllamaOrganizer:
    """Organizer backed by a local Ollama model, with a Heuristic fallback."""

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        chat: ChatClient = _ollama_chat,
        fallback: Organizer | None = None,
    ) -> None:
        self._model = model
        self._chat = chat
        self._fallback: Organizer = fallback or HeuristicOrganizer()

    def organize(self, original: Original) -> ProposedNote:
        try:
            raw = self._chat(self._model, build_prompt(original.text))
            return parse_proposed(raw, original)
        except Exception:  # noqa: BLE001 - never break the pipeline; fall back to the baseline
            # Any model/parse/transport failure (bad JSON, model not pulled, Ollama not
            # running -> ConnectionError) degrades to the deterministic HeuristicOrganizer.
            return self._fallback.organize(original)
