"""Lossless round-trip tests for captured Originals (SPEC US-2 / QAS-2).

The store must return every captured selection byte-for-byte identical and never
mutate it. We exercise a curated adversarial corpus plus seeded random unicode.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from grandplan.core.models import Original, Source
from grandplan.core.store import InMemoryOriginalStore, JsonlOriginalStore, OriginalStore

ADVERSARIAL: tuple[str, ...] = (
    "",
    " ",
    "\n\n\t  trailing and leading whitespace  \n",
    "plain ascii note about a project deadline",
    "unicode: café résumé Москва 北京 \U0001f9e0\U0001f4dd",
    "emoji \U0001f600\U0001f680 and ZWJ \U0001f469‍\U0001f4bb",
    "rtl שלום عالم mixed with ltr",
    "code:\n```python\ndef f(x: int) -> int:\n\treturn x + 1  # tab\n```",
    "windows\r\nline\r\nendings and a lone \r return",
    "line and separators",
    'json-ish: {"key": "value", "n": 1, "arr": [1, 2, 3]}',
    "very " * 5000 + "long",
)


def _seeded_random_strings(n: int, seed: int = 1130) -> list[str]:
    rng = random.Random(seed)
    out: list[str] = []
    for _ in range(n):
        length = rng.randint(0, 200)
        chars = (chr(rng.randint(0, 0x10FFFF)) for _ in range(length))
        out.append("".join(c for c in chars if not 0xD800 <= ord(c) <= 0xDFFF))
    return out


CORPUS: tuple[str, ...] = ADVERSARIAL + tuple(_seeded_random_strings(200))


def _stores(tmp_path: Path) -> list[OriginalStore]:
    return [InMemoryOriginalStore(), JsonlOriginalStore(tmp_path / "originals.jsonl")]


@pytest.mark.parametrize("text", CORPUS)
def test_roundtrip_preserves_text_byte_for_byte(text: str, tmp_path: Path) -> None:
    source = Source(app="Notepad", title="note.txt")
    created = "2026-06-15T12:00:00Z"
    for store in _stores(tmp_path):
        original = Original.capture(text, source, created)
        store.add(original)
        got = store.get(original.id)
        assert got is not None
        assert got.text == text
        assert got.text.encode("utf-8") == text.encode("utf-8")
        assert got == original


def test_store_is_append_only_and_idempotent(tmp_path: Path) -> None:
    for store in _stores(tmp_path):
        first = Original.capture("first", Source(app="A"), "2026-06-15T00:00:00Z")
        store.add(first)
        store.add(first)  # idempotent on identical content
        got = store.get(first.id)
        assert got is not None
        assert got.text == "first"
        assert len(store.all()) == 1


def test_jsonl_persists_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "originals.jsonl"
    text = "persist me: café \U0001f9e0\nwith newline"
    original = Original.capture(text, Source(app="X"), "2026-06-15T00:00:00Z")
    JsonlOriginalStore(path).add(original)
    got = JsonlOriginalStore(path).get(original.id)
    assert got is not None
    assert got.text == text
