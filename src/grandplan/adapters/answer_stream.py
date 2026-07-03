"""AnswerStreamFilter — live-print only the "answer" value from a streaming JSON chat reply.

Chat replies are grammar-constrained JSON (`{"answer": …, "sources": […]}`), which makes replies
robust to parse — but means naive token streaming would show the user raw JSON syntax while the
model types. This filter sits between the transport's raw deltas and the terminal: it finds the
`"answer"` string value wherever it appears and emits its DECODED text incrementally, staying
silent before it opens and after it closes.

Chunk boundaries can land anywhere — mid-key, mid-escape, even inside a `\\uXXXX` sequence — so
the filter re-scans an accumulated buffer and emits only the not-yet-emitted suffix of the decoded
value. Buffers are the size of one model reply (a few KB); simplicity beats a char-level state
machine here. Pure and exhaustively unit-tested (`tests/adapters/test_answer_stream.py`).
"""

from __future__ import annotations

import re

_ANSWER_OPEN = re.compile(r'"answer"\s*:\s*"')
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class AnswerStreamFilter:
    """Feed raw reply chunks in; get printable answer-text deltas out."""

    def __init__(self) -> None:
        self._buffer = ""
        self._value_start: int | None = None  # index just past the value's opening quote
        self._emitted = 0  # decoded chars already handed to the caller
        self._closed = False

    def feed(self, chunk: str) -> str:
        """Consume one raw delta; return the newly printable portion of the answer ("" if none)."""
        if self._closed:
            return ""
        self._buffer += chunk
        if self._value_start is None:
            match = _ANSWER_OPEN.search(self._buffer)
            if match is None:
                return ""
            self._value_start = match.end()
        decoded, closed = _decode_partial(self._buffer[self._value_start :])
        self._closed = closed
        delta = decoded[self._emitted :]
        self._emitted = len(decoded)
        return delta


def _decode_partial(raw: str) -> tuple[str, bool]:
    """Decode a (possibly unterminated) JSON string body: (text so far, closed?).

    Stops cleanly before an incomplete trailing escape (`\\` or partial `\\uXX…`) so a chunk
    boundary inside an escape sequence never emits garbage — the next feed completes it.
    """
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == '"':
            return "".join(out), True
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        if i + 1 >= len(raw):
            break  # escape not yet complete — wait for the next chunk
        esc = raw[i + 1]
        if esc == "u":
            if i + 6 > len(raw):
                break  # \uXXXX not yet complete
            try:
                out.append(chr(int(raw[i + 2 : i + 6], 16)))
            except ValueError:
                out.append(raw[i : i + 6])  # malformed escape — pass through verbatim
            i += 6
            continue
        out.append(_ESCAPES.get(esc, esc))
        i += 2
    return "".join(out), False
