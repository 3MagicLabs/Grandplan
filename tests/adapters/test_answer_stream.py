"""AnswerStreamFilter: live-print ONLY the "answer" value from a streaming JSON reply.

Chat replies are grammar-constrained JSON, so raw token streaming would show the user
`{"answer": "…` syntax. The filter turns raw chunks into printable answer text incrementally —
tolerating chunk boundaries ANYWHERE: mid-key, mid-escape, even inside a \\uXXXX sequence.
"""

from __future__ import annotations

import json

import pytest

from grandplan.adapters.answer_stream import AnswerStreamFilter


def _stream(raw: str, size: int) -> str:
    """Feed `raw` in `size`-char chunks; return everything the filter emitted."""
    stream_filter = AnswerStreamFilter()
    return "".join(stream_filter.feed(raw[i : i + size]) for i in range(0, len(raw), size))


@pytest.mark.parametrize("size", [1, 2, 3, 7, 1000])
def test_emits_exactly_the_answer_value_at_any_chunking(size: int) -> None:
    raw = '{"answer": "Postgres, per your decision.", "sources": ["a"]}'
    assert _stream(raw, size) == "Postgres, per your decision."


@pytest.mark.parametrize("size", [1, 2, 5])
def test_decodes_escapes_split_across_chunks(size: int) -> None:
    answer = 'line one\nline "two" \\ tab\t✨ ünïcode'
    raw = json.dumps({"answer": answer, "sources": []})
    assert _stream(raw, size) == answer


@pytest.mark.parametrize("size", [1, 4])
def test_answer_key_not_first_still_found(size: int) -> None:
    raw = '{"sources": ["abc123"], "answer": "found me"}'
    assert _stream(raw, size) == "found me"


def test_nothing_emitted_before_the_answer_value_or_after_it_closes() -> None:
    stream_filter = AnswerStreamFilter()
    assert stream_filter.feed('{"answer"') == ""  # key seen, value not open yet
    assert stream_filter.feed(': "hi') == "hi"
    assert stream_filter.feed('", "sources": ["x"]}') == ""  # closed → trailing JSON suppressed


def test_no_answer_key_emits_nothing() -> None:
    assert _stream('{"sources": ["a"], "other": 1}', 3) == ""


def test_truncated_stream_emits_what_arrived() -> None:
    # Context window ran out mid-answer: everything decoded so far was already shown live.
    assert _stream('{"answer": "partial thou', 2) == "partial thou"
