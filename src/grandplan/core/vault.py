"""MarkdownVaultWriter — renders an approved note as Obsidian-friendly Markdown.

Output: YAML frontmatter (JSON-encoded values, so titles/tags are always valid YAML and
dependency-free), a title heading, the organized body, typed `[[wikilinks]]` that **resolve**
to real notes, and a **verbatim** "Source (original)" block in a dynamically-sized code fence
so any backticks in the original cannot break it. The verbatim original keeps the note lossless
on disk too.

Link resolution (SPEC US-5 "targets are real notes, no broken links"): files are named
`<slug>-<id>.md`, links render as `[[<slug>-<id>|<title>]]` (resolves to the file, displays the
title), and every note also carries `aliases: ["<id>"]` so a bare-id reference resolves too.
The `source` object is flattened into scalar `source_*` keys so Obsidian's property UI renders
it cleanly instead of as a raw JSON string.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from grandplan.core.models import Edge, Note, Original

_SLUG = re.compile(r"[^0-9a-z]+")


def note_filename(note: Note) -> str:
    """Stable, human-readable, content-addressed file stem for a note (no extension)."""
    return f"{_slug(note.title)}-{note.id}"


class MarkdownVaultWriter:
    """Write notes as `.md` files into a vault directory."""

    def __init__(self, vault_dir: Path) -> None:
        self._dir = vault_dir

    def write(
        self,
        note: Note,
        original: Original,
        links: tuple[Edge, ...],
        *,
        targets: Mapping[str, Note] | None = None,
    ) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{note_filename(note)}.md"
        path.write_text(render_markdown(note, original, links, targets=targets), encoding="utf-8")
        return path


def render_markdown(
    note: Note,
    original: Original,
    links: tuple[Edge, ...],
    *,
    targets: Mapping[str, Note] | None = None,
) -> str:
    parts = [_frontmatter(note, original), "", f"# {note.title}", "", note.body.strip()]
    wikilinks = _wikilinks(note.id, links, targets or {})
    if wikilinks:
        parts += ["", "## Links", *wikilinks]
    parts += ["", "## Source (original)", "", _fenced(original.text)]
    return "\n".join(parts) + "\n"


def _frontmatter(note: Note, original: Original) -> str:
    fields: dict[str, object] = {
        "id": note.id,
        "aliases": [note.id],  # so `[[<id>]]` references resolve to this file in Obsidian
        "type": note.type.value,
        "status": note.status.value,
        "horizon": note.horizon.value,
        "tags": list(note.tags),
        "created": original.created,
        # Flattened so Obsidian's property editor shows clean scalars (not a raw JSON object).
        "source_app": original.source.app,
        "source_title": original.source.title,
        "source_uri": original.source.uri,
        "original_id": original.id,
    }
    body = "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items()
    )
    return f"---\n{body}\n---"


def _wikilinks(note_id: str, links: tuple[Edge, ...], targets: Mapping[str, Note]) -> list[str]:
    rendered: list[str] = []
    for edge in links:
        if edge.source_id != note_id:
            continue
        target = targets.get(edge.target_id)
        link = (
            f"[[{note_filename(target)}|{target.title}]]"
            if target is not None
            else f"[[{edge.target_id}]]"
        )
        rendered.append(f"- {edge.kind.value} {link}")
    return rendered


def _fenced(text: str) -> str:
    longest = run = 0
    for char in text:
        run = run + 1 if char == "`" else 0
        longest = max(longest, run)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def _slug(title: str) -> str:
    slug = _SLUG.sub("-", title.lower()).strip("-")
    return slug[:50] or "note"
