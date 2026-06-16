"""Append-only, lossless stores for captured Originals (the Repository port).

Invariant: an Original, once stored, is returned byte-for-byte identical and is never
mutated or overwritten (SPEC §6d). Implementations are append-only and idempotent on
identical content (same content-addressed id).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from grandplan.core.models import Original, Source


class OriginalStore(Protocol):
    """Port: persist and retrieve captured Originals without ever altering them."""

    def add(self, original: Original) -> None: ...

    def get(self, original_id: str) -> Original | None: ...

    def all(self) -> tuple[Original, ...]: ...


class InMemoryOriginalStore:
    """In-memory append-only store (the fake used by the core's tests)."""

    def __init__(self) -> None:
        self._items: dict[str, Original] = {}

    def add(self, original: Original) -> None:
        # Append-only: never overwrite or mutate an already-stored original.
        self._items.setdefault(original.id, original)

    def get(self, original_id: str) -> Original | None:
        return self._items.get(original_id)

    def all(self) -> tuple[Original, ...]:
        return tuple(self._items.values())


class JsonlOriginalStore:
    """Append-only JSON-Lines store; proves losslessness through persistence.

    Each record is one line of UTF-8 JSON (`ensure_ascii=False`), so the verbatim
    text survives a write/read round-trip — control characters are JSON-escaped, so
    no original byte is altered by line handling.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._items: dict[str, Original] = {}
        if path.exists():
            self._load()

    def _load(self) -> None:
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                record = line.rstrip("\n")
                if not record:
                    continue
                original = self._decode(record)
                self._items.setdefault(original.id, original)

    @staticmethod
    def _decode(record: str) -> Original:
        data = json.loads(record)
        return Original(
            id=data["id"],
            text=data["text"],
            source=Source(
                app=data["source"]["app"],
                title=data["source"]["title"],
                uri=data["source"]["uri"],
            ),
            created=data["created"],
        )

    def add(self, original: Original) -> None:
        if original.id in self._items:
            return  # append-only + idempotent on identical content
        payload = {
            "id": original.id,
            "text": original.text,
            "source": {
                "app": original.source.app,
                "title": original.source.title,
                "uri": original.source.uri,
            },
            "created": original.created,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._items[original.id] = original

    def get(self, original_id: str) -> Original | None:
        return self._items.get(original_id)

    def all(self) -> tuple[Original, ...]:
        return tuple(self._items.values())
