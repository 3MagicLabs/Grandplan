"""Core domain models for grandplan.

An `Original` is a captured selection preserved **verbatim**. It is immutable and is
never mutated after capture — the lossless guarantee (SPEC US-2 / QAS-2 / §6d).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    """Where a captured selection came from."""

    app: str
    title: str = ""
    uri: str = ""


@dataclass(frozen=True)
class Original:
    """A captured selection, preserved verbatim. Immutable.

    `id` is a deterministic content hash, so identical captures collapse to one
    record (natural exact-duplicate handling) without any clock or randomness.
    """

    id: str
    text: str
    source: Source
    created: str  # ISO-8601 timestamp, supplied by the caller (no hidden clock)

    @staticmethod
    def capture(text: str, source: Source, created: str) -> Original:
        """Create an Original with a deterministic content-addressed id."""
        parts = (text, source.app, source.title, source.uri, created)
        digest = hashlib.sha256(b"\x00".join(p.encode("utf-8") for p in parts))
        return Original(id=digest.hexdigest(), text=text, source=source, created=created)
