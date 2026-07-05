"""Shared Ollama JSON-chat plumbing for the local-LLM adapters (organize, reconcile, place, …).

Every adapter talks to Ollama the same way — `format="json"`, temperature 0, the model kept warm —
and then parses a single JSON object out of the reply. Two robustness concerns that used to be
copy-pasted (and one that was simply missing) live here so every adapter gets them for free:

1. **`num_ctx`** — without a large enough context window a long capture leaves no room for the model
   to finish the JSON, so the grammar-constrained (`format="json"`) output is *truncated* mid-object.
   A bare `json.loads` then fails with `Expecting ',' delimiter` at the end of the string and the
   whole call silently falls back. We set a generous default window so the reply fits.

2. **`loads_lenient`** — even with room a reply can still be truncated (a very long note), wrapped in
   a ``` ```json ``` fence, or trailed by a stray sentence. Rather than discard a whole
   organize/reconcile/placement, we extract the first JSON value and *complete* a truncated one, so a
   usable result survives instead of degrading to the keyword baseline.

The `chat_json` transport needs a running Ollama, so it is `pragma: no cover`; `loads_lenient` is
pure and exhaustively unit-tested (`tests/test_ollama_json.py`).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Context window for one local-LLM call. The capture prompt (instruction + the captured note) plus
# the JSON reply must fit, or generation stops mid-object and the JSON is truncated. 8192 leaves
# ample room for a typical capture + organized body while staying memory-safe on the project's
# "16 GB RAM, no GPU" target. `loads_lenient` is the safety net for a reply that still overruns it.
#
# Memory trade-off (#2): the window sizes Ollama's KV cache — roughly linear in num_ctx, on the
# order of hundreds of MB extra at 8192 for the ~4B capture models. Set GRANDPLAN_NUM_CTX to tune:
# lower (e.g. 2048) frees RAM on tight machines at the cost of truncating very long captures;
# higher (e.g. 16384) fits huge captures if RAM allows. One knob for every adapter.
DEFAULT_NUM_CTX = 8192
_ENV_NUM_CTX = "GRANDPLAN_NUM_CTX"


def default_num_ctx() -> int:
    """The context window to use: `GRANDPLAN_NUM_CTX` when set to a positive int, else 8192.

    Read per call (not at import), so the env var works however the process is launched; a
    malformed value is logged and ignored, never a crash at capture time.
    """
    raw = os.environ.get(_ENV_NUM_CTX, "")
    if not raw:
        return DEFAULT_NUM_CTX
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        logger.warning(
            "%s=%r is not a positive integer; using %d", _ENV_NUM_CTX, raw, DEFAULT_NUM_CTX
        )
        return DEFAULT_NUM_CTX
    return value


_OPENERS = {"{": "}", "[": "]"}
_CLOSERS = frozenset({"}", "]"})


def chat_json(
    model: str, prompt: str, *, timeout: float, num_ctx: int | None = None
) -> str:  # pragma: no cover - needs a running Ollama
    """One JSON-mode chat turn against a local Ollama model; returns the raw reply content.

    Centralises the call so `format`, `temperature`, `keep_alive`, and especially `num_ctx` are set
    once for every adapter (previously each adapter inlined this and none set `num_ctx`).
    `num_ctx=None` (the normal case) resolves via `default_num_ctx()` — one env knob
    (GRANDPLAN_NUM_CTX) tunes the memory/window trade-off for every adapter at once.
    """
    try:
        import ollama
    except ImportError as exc:
        raise RuntimeError(
            f"ollama client unavailable ({exc}); `pip install grandplan[llm]`"
        ) from exc
    response = ollama.Client(timeout=timeout).chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={
            "temperature": 0,
            "num_ctx": num_ctx if num_ctx is not None else default_num_ctx(),
        },
        keep_alive="30m",
    )
    return str(response["message"]["content"])


def chat_json_stream(
    model: str,
    prompt: str,
    *,
    timeout: float,
    on_delta: Any,
    num_ctx: int | None = None,
) -> str:  # pragma: no cover - needs a running Ollama
    """Like `chat_json`, but streams: `on_delta(chunk)` per raw content piece; returns the full text.

    Same options/knobs as `chat_json` (format=json, temperature 0, keep_alive, num_ctx). Callers
    filter the raw JSON deltas into printable text (`answer_stream.AnswerStreamFilter`) — the
    perceived-latency win: the user watches the answer type instead of staring at a silent prompt.
    """
    try:
        import ollama
    except ImportError as exc:
        raise RuntimeError(
            f"ollama client unavailable ({exc}); `pip install grandplan[llm]`"
        ) from exc
    pieces: list[str] = []
    for part in ollama.Client(timeout=timeout).chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={
            "temperature": 0,
            "num_ctx": num_ctx if num_ctx is not None else default_num_ctx(),
        },
        keep_alive="30m",
        stream=True,
    ):
        chunk = str(part["message"]["content"])
        if chunk:
            pieces.append(chunk)
            on_delta(chunk)
    return "".join(pieces)


def loads_lenient(raw: str) -> Any:
    """Parse a JSON value from a model reply, tolerating fences, surrounding prose, and truncation.

    Strategy: from the first `{`/`[`, (1) try a straight decode (`raw_decode` ignores any trailing
    text, so a fenced or prose-wrapped object parses); (2) if that fails the value was truncated when
    the model hit its context window — complete it by closing the open string and brackets, trimming
    the dangling trailing member if a straight close still won't parse. Recovery works on the *first*
    opener only, so a complete nested value (e.g. the `tags` array) is never mistaken for the whole
    reply. Raises `ValueError` when no JSON object/array can be recovered (callers fall back/retry).
    """
    text = raw.strip()
    start = next((i for i, ch in enumerate(text) if ch in _OPENERS), None)
    if start is None:
        raise ValueError("no JSON object or array found in model output")
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(text, start)  # handles prose/fences around a complete value
        return obj
    except json.JSONDecodeError:
        pass
    recovered = _complete(text[start:], decoder)  # truncated → close it
    if recovered is not None:
        return recovered
    raise ValueError("could not recover JSON from model output")


def _complete(candidate: str, decoder: json.JSONDecoder) -> Any:
    """Try to parse a truncated JSON value: close it as-is, else trim back to a member boundary."""
    for repaired in _completions(candidate):
        try:
            obj, _ = decoder.raw_decode(repaired)
            return obj
        except json.JSONDecodeError:
            continue
    return None


def _completions(candidate: str) -> list[str]:
    """Candidate repairs for a truncated value, best first: close as-is, then drop the incomplete
    trailing member at each earlier comma boundary, then fall back to an empty outer container."""
    repairs = [_close(candidate)]
    for cut in reversed(_member_boundaries(candidate)):
        repairs.append(_close(candidate[:cut]))
    repairs.append(_close(candidate[:1]))  # last resort: just the outermost {} / []
    return repairs


def _close(s: str) -> str:
    """Close any open string and brackets in `s`, dropping a dangling trailing separator."""
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in s:
        if escape:
            escape = False
            continue
        if in_string:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in _OPENERS:
            stack.append(_OPENERS[ch])
        elif ch in _CLOSERS and stack:
            stack.pop()
    out = s
    if in_string:
        out += '"'  # close the truncated string value
    out = out.rstrip()
    while out and out[-1] in ",:":  # a member with no value yet (e.g. `"body":`) — drop it
        out = out[:-1].rstrip()
    out += "".join(reversed(stack))
    return out


def _member_boundaries(s: str) -> list[int]:
    """Indexes of the commas that separate members (ignoring commas inside strings); `s[:i]` can be
    closed into a smaller-but-valid value by dropping the incomplete member that followed."""
    bounds: list[int] = []
    in_string = False
    escape = False
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if in_string:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == ",":
            bounds.append(i)
    return bounds
