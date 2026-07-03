"""KB agent — Ask mode (SPEC-AGENT-KB P1): retrieval-grounded Q&A over the vault, read-only.

The first slice of the knowledge-base agent: embed the question, pull the most-similar notes from
the repository, and have a local model answer **only from those notes**, citing note ids. Zero write
risk — it drives the same read primitives as `grandplan mcp`, never the write tools.

Two-model strategy (SPEC-AGENT-KB §1): the KB agent gets its own, heavier default model
(`qwen2.5:14b`) because it runs infrequently — it must never be silently coupled to the
latency-tuned capture model. Degradation chain when that model isn't available (spike §7 resolved):
KB model → capture model → **retrieval-only** (the ranked notes, clearly labeled, no synthesis).
Ask never fails hard: the vault is still searchable with no model at all.

Anti-hallucination mirrors the organizer's resource containment: a cited id the model invented
(not among the retrieved notes) is dropped. The transport is injected, so prompt assembly, citation
validation, and the fallback chain are unit-tested (`tests/adapters/test_kb_ask.py`); a real Ollama
integration-tests it on the user's machine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from grandplan.adapters._ollama import chat_json, loads_lenient
from grandplan.adapters.ollama_organizer import DEFAULT_MODEL, OLLAMA_TIMEOUT_S, ChatClient
from grandplan.core.ports import Embedder, NoteRepository

logger = logging.getLogger(__name__)

# The KB agent's own default (SPEC-AGENT-KB): a 14B reasoner is affordable here because Ask is
# infrequent and interactive-but-patient, unlike the per-capture organize loop. Q4_K_M fits the
# 16 GB no-GPU target. Pull once: `ollama pull qwen2.5:14b` — or pass --kb-model to use another.
KB_DEFAULT_MODEL = "qwen2.5:14b"
_TOP_K = 6
_BODY_SNIPPET = 700  # chars of each note's body shown to the model — richer than reconcile's 280
# because grounded answering needs content, while the prompt must still fit DEFAULT_NUM_CTX.
_MIN_SCORE = 0.05  # drop notes with ~zero similarity so an unrelated vault can't pollute grounding

_INSTRUCTION = (
    "You answer a question about the user's personal notes. Use ONLY the notes below — do not add "
    "outside facts; if the notes do not contain the answer, say so. "
    'Return ONLY a JSON object with keys: "answer" (a direct, concise answer in plain text, '
    'grounded in the notes) and "sources" (array of the ids of the notes you actually used).'
)


@dataclass(frozen=True)
class AskAnswer:
    """The outcome of one Ask: synthesized text + which notes ground it.

    `model` records which model actually answered; None means the retrieval-only degradation —
    `sources` then carries the ranked matches and `text` is empty (the caller labels the mode).
    """

    text: str
    sources: tuple[tuple[str, str], ...]  # (note_id, title), in citation/rank order
    model: str | None


def build_ask_prompt(question: str, notes: Sequence[tuple[str, str, str]]) -> str:
    """Assemble the grounded-QA prompt from `(id, title, body)` retrieval hits (pure)."""
    lines = [
        f"- id={note_id} title={title!r}\n  {body[:_BODY_SNIPPET]}"
        for note_id, title, body in notes
    ]
    return f"{_INSTRUCTION}\n\nNOTES:\n" + "\n".join(lines) + f"\n\nQUESTION:\n{question}"


def parse_answer(raw: str, allowed_ids: frozenset[str]) -> tuple[str, tuple[str, ...]]:
    """Extract (answer, cited ids) from a model reply; invented ids are dropped (containment)."""
    data = loads_lenient(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    text = str(data.get("answer") or "").strip()
    if not text:
        raise ValueError("model returned no answer")
    raw_sources = data.get("sources", [])
    cited = (
        tuple(str(s) for s in raw_sources if str(s) in allowed_ids)
        if isinstance(raw_sources, list)
        else ()
    )
    return text, cited


def _ollama_chat(model: str, prompt: str) -> str:  # pragma: no cover - needs a running Ollama
    return chat_json(model, prompt, timeout=OLLAMA_TIMEOUT_S)


def _ollama_chat_stream(  # pragma: no cover - needs a running Ollama
    model: str, prompt: str, on_delta: Callable[[str], None]
) -> str:
    """Streaming twin of `_ollama_chat` — the SAME patchable module seam contract: tests/config
    that replace the transports patch these two names and nothing else reaches the network."""
    from grandplan.adapters._ollama import chat_json_stream

    return chat_json_stream(model, prompt, timeout=OLLAMA_TIMEOUT_S, on_delta=on_delta)


class KbAsk:
    """Ask the vault a question: retrieve → ground → answer with citations (read-only)."""

    def __init__(
        self,
        *,
        repo: NoteRepository,
        embedder: Embedder,
        chat: ChatClient | None = None,
        model: str = KB_DEFAULT_MODEL,
        fallback_model: str = DEFAULT_MODEL,
        top_k: int = _TOP_K,
    ) -> None:
        self._repo = repo
        self._embedder = embedder
        # Resolved at construction (not a def-time default) so tests can patch the module transport.
        self._chat = chat or _ollama_chat
        self._model = model
        self._fallback_model = fallback_model
        self._top_k = top_k

    def ask(self, question: str) -> AskAnswer:
        hits = self._repo.most_similar(
            self._embedder.embed(question), limit=self._top_k, threshold=_MIN_SCORE
        )
        if not hits:
            return AskAnswer(text="", sources=(), model=None)
        titles = {note.id: note.title for note, _score in hits}
        prompt = build_ask_prompt(question, [(n.id, n.title, n.body) for n, _ in hits])
        for model in self._models():
            try:
                text, cited = parse_answer(self._chat(model, prompt), frozenset(titles))
            except Exception as exc:  # noqa: BLE001 - model not pulled, Ollama down, bad JSON
                logger.warning("ask with %s failed; trying next fallback: %s", model, exc)
                continue
            return AskAnswer(
                text=text, sources=tuple((cid, titles[cid]) for cid in cited), model=model
            )
        # Retrieval-only: no local model produced an answer — the ranked matches are still useful.
        return AskAnswer(
            text="", sources=tuple((n.id, n.title) for n, _ in hits), model=None
        )

    def _models(self) -> tuple[str, ...]:
        """KB model first, capture model as fallback — deduped when they're the same."""
        if self._fallback_model == self._model:
            return (self._model,)
        return (self._model, self._fallback_model)
