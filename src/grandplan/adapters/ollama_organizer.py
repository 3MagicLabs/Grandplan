"""OllamaOrganizer — a local-LLM Organizer adapter (offline, via Ollama).

Drop-in for the `Organizer` port: asks a local model (Ollama on localhost:11434) for a note's
**title, type, tags, and an organized body** as JSON, then validates and maps them. The model
*summarizes and organizes* the capture into a clean atomic note (SPEC US-3) — but the captured
Original is **never destroyed**: it is preserved verbatim and rendered in the note's "Source
(original)" block (US-2), so enhancement is lossless. On malformed output the call is retried
once with a stricter instruction; on repeated failure it falls back to the HeuristicOrganizer so
the pipeline never breaks. If the model omits a body, the verbatim original is kept as the body
(never an invalid note).

The HTTP call is injected (`chat`), so parsing/validation/retry/fallback are unit-tested here;
running a real Ollama + pulled model integration-tests it on the user's machine
(`pip install grandplan[llm]`).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

from grandplan.core.models import NoteType, Original, ProposedNote, default_horizon
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.ports import Organizer
from grandplan.core.resources import Resource, ResourceKind, extract_resources

logger = logging.getLogger(__name__)


class OrganizerUnavailable(RuntimeError):
    """The required local model could not produce a valid note (Ollama down / model not pulled).

    Raised only in `require=True` mode (PR-F, RC1): when the user has asked for LLM organization, a
    silent degradation to the keyword heuristic is a bug — they get this actionable error instead,
    and the verbatim capture is preserved in the inbox (added before organize runs, `pipeline.propose`).
    """

    def __init__(self, model: str) -> None:
        super().__init__(
            f"local model {model!r} did not return a usable note — is Ollama running and the "
            f"model pulled? Try `ollama serve` + `ollama pull {model}`, or use the offline "
            f"baseline (--no-llm)."
        )
        self.model = model


ChatClient = Callable[[str, str], str]
# Default sized for the project's "runs on 16 GB RAM, no GPU" constraint (ADR-0006): llama3.2:3b
# (~2 GB resident) keeps capture memory-safe on modest hardware. Swap in a stronger model with
# --model on machines with headroom (e.g. qwen2.5:7b ~5 GB, gemma2:9b). All local/offline via Ollama.
DEFAULT_MODEL = "llama3.2:3b"
# Hard wall-clock cap (seconds) on ONE local-LLM call. Without it the underlying httpx client has no
# timeout, so a stalled/loading model pins the capture worker forever and breaks clean shutdown
# (robustness audit, HIGH). On timeout the call raises → the adapter's except catches it and falls
# back to the deterministic baseline (or raises OrganizerUnavailable under require=True).
OLLAMA_TIMEOUT_S = 180.0
_MAX_TITLE = 80
_VALID_TYPES = {note_type.value: note_type for note_type in NoteType}
_VALID_RESOURCE_KINDS = {kind.value: kind for kind in ResourceKind}

_INSTRUCTION = (
    "You organize a captured note into a clean, self-contained atomic note. "
    'Return ONLY a JSON object with keys: "title" (concise, specific, no quotes), '
    '"type" (one of: ' + ", ".join(_VALID_TYPES) + "), "
    '"tags" (array of 1-5 short lowercase topical tags), '
    '"body" (a clean Markdown rewrite that ENHANCES the note: start with ONE line summarising it, '
    "then the key points as bullets; and WHEN the note is actionable (a task, project, goal, or "
    'anything implying work to do) add a "## Next steps" section listing concrete, feasible actions '
    "as `- [ ]` checklist items — each small enough to act on and ordered logically. Clarify and "
    "organise the wording, but DO NOT invent facts, names, numbers, or commitments not implied by "
    "the note), and "
    '"resources" (array of any referenced artifacts as {"kind": one of '
    + ", ".join(_VALID_RESOURCE_KINDS)
    + ', "ref": the URL/path or, for a placeholder, a short description, "label": optional}; '
    "use 'placeholder' for an artifact the note says should be made but does not exist yet). "
    "Do not echo the original verbatim text — it is preserved separately."
)


def build_prompt(text: str, *, strict: bool = False) -> str:
    repair = (
        "\n\nIMPORTANT: your previous reply was not valid. Reply with ONLY a single valid JSON "
        "object and nothing else."
        if strict
        else ""
    )
    return f"{_INSTRUCTION}{repair}\n\nNOTE:\n{text}"


# A model refusal/apology must not become a note title/body — detect and reject so the caller
# retries then falls back to the deterministic organizer (which keeps the user's actual text).
_REFUSAL = re.compile(
    r"\b(?:i (?:cannot|can't|can not|am unable|'m unable|am sorry|'m sorry|am not able)"
    r"|as an ai\b|unable to (?:assist|help|comply|provide|fulf[il]l)"
    r"|cannot (?:assist|help|comply|fulf[il]l|provide))",
    re.IGNORECASE,
)


def parse_proposed(raw: str, original: Original) -> ProposedNote:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    title = (str(data.get("title") or "").strip() or _first_line(original.text))[:_MAX_TITLE]
    if _REFUSAL.search(title) or _REFUSAL.search(str(data.get("body") or "")[:120]):
        raise ValueError("model output looks like a refusal/error, not a note")
    note_type = _VALID_TYPES.get(str(data.get("type", "")).strip().lower(), NoteType.IDEA)
    tags_raw = data.get("tags", [])
    tags = (
        tuple(str(tag).strip() for tag in tags_raw if str(tag).strip())
        if isinstance(tags_raw, list)
        else ()
    )
    # Use the model's organized body when present; otherwise keep the verbatim original so the
    # note is never invalid (US-3) and never lossy (the Original is rendered in full regardless).
    body = str(data.get("body") or "").strip() or original.text.strip()
    return ProposedNote(
        original_id=original.id,
        title=title,
        body=body,
        type=note_type,
        tags=tags,
        horizon=default_horizon(note_type),  # goals/projects rise above the action band
        resources=_parse_resources(data.get("resources"), original.text),
    )


def _parse_resources(raw: object, text: str) -> tuple[Resource, ...]:
    """Validate the model's `resources` array (skipping malformed entries); fall back to the
    deterministic extractor when the model omits it or returns nothing usable (PR-D).

    Anti-hallucination: a concrete reference (link/image/file — i.e. a real URL or path) is only
    kept if it actually appears in the capture text. Small models confidently invent plausible links
    (e.g. a `docs.google.com/...` that was never there); those are dropped. A `placeholder` is a
    *description* of an expected, not-yet-existing artifact, so it may legitimately be model-authored.
    """
    haystack = text.lower()
    parsed: list[Resource] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            kind = _VALID_RESOURCE_KINDS.get(str(item.get("kind", "")).strip().lower())
            # Collapse all whitespace (incl. newlines) so a model-supplied value can't inject a new
            # Markdown line/heading into the rendered `## Resources` section.
            ref = " ".join(str(item.get("ref") or "").split())
            if kind is None or not ref:
                continue
            if kind is not ResourceKind.PLACEHOLDER and ref.lower() not in haystack:
                continue  # a link/file the model invented (not in the capture) → hallucination, drop it
            label = " ".join(str(item.get("label") or "").split())
            parsed.append(Resource(kind=kind, ref=ref, label=label))
    return tuple(parsed) if parsed else extract_resources(text)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return "Untitled note"


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


class OllamaOrganizer:
    """Organizer backed by a local Ollama model, with a Heuristic fallback."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        chat: ChatClient = _ollama_chat,
        fallback: Organizer | None = None,
        require: bool = False,
    ) -> None:
        self._model = model
        self._chat = chat
        # require=True (PR-F, RC1): no fallback — a failure raises `OrganizerUnavailable` so a
        # missing/unreachable model is loud, never silent keyword garbage. require=False (default)
        # keeps the deterministic baseline so the offline path and existing behaviour are unchanged.
        self._fallback: Organizer | None = None if require else (fallback or HeuristicOrganizer())

    def organize(self, original: Original) -> ProposedNote:
        # Validate-and-retry (SPEC US-3): try once, then once more with a stricter instruction.
        for strict in (False, True):
            proposed = self._attempt(original, strict=strict)
            if proposed is not None:
                return proposed
        # Exhausted: degrade to the deterministic baseline, or — when the LLM was required — fail
        # loud so the user knows the model didn't run (the capture is already safe in the inbox).
        if self._fallback is None:
            raise OrganizerUnavailable(self._model)
        return self._fallback.organize(original)

    def _attempt(self, original: Original, *, strict: bool) -> ProposedNote | None:
        """One organize attempt; returns None on any model/parse/transport failure."""
        try:
            raw = self._chat(self._model, build_prompt(original.text, strict=strict))
            return parse_proposed(raw, original)
        except Exception as exc:  # noqa: BLE001 - bad JSON, model not pulled, or Ollama not running
            # Surface the degradation (US-7 observability): silent fallback hid a misconfigured or
            # unreachable Ollama. WARNING, not ERROR — the pipeline still degrades gracefully.
            logger.warning("LLM organize attempt failed (strict=%s); falling back: %s", strict, exc)
            return None
