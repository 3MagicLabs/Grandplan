"""MarkdownVaultWriter — renders an approved note as Obsidian-friendly Markdown.

Output: YAML frontmatter (JSON-encoded values, so titles/tags are always valid YAML and
dependency-free), a title heading, the organized body, typed `[[wikilinks]]`, and a
**verbatim** "Source (original)" block in a dynamically-sized code fence so any backticks in
the original cannot break it. The verbatim original keeps the note lossless on disk too.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from grandplan.core.models import Edge, Note, Original

_SLUG = re.compile(r"[^0-9a-z]+")


class MarkdownVaultWriter:
    """Write notes as `.md` files into a vault directory."""

    def __init__(self, vault_dir: Path) -> None:
        self._dir = vault_dir

    def write(self, note: Note, original: Original, links: tuple[Edge, ...]) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{_slug(note.title)}-{note.id}.md"
        path.write_text(render_markdown(note, original, links), encoding="utf-8")
        return path


def render_markdown(note: Note, original: Original, links: tuple[Edge, ...]) -> str:
    parts = [_frontmatter(note, original), "", f"# {note.title}", "", note.body.strip()]
    wikilinks = _wikilinks(note.id, links)
    if wikilinks:
        parts += ["", "## Links", *wikilinks]
    parts += ["", "## Source (original)", "", _fenced(original.text)]
    return "\n".join(parts) + "\n"


def _frontmatter(note: Note, original: Original) -> str:
    fields: dict[str, object] = {
        "id": note.id,
        "type": note.type.value,
        "status": note.status.value,
        "horizon": note.horizon.value,
        "tags": list(note.tags),
        "created": original.created,
        "source": {
            "app": original.source.app,
            "title": original.source.title,
            "uri": original.source.uri,
        },
        "original_id": original.id,
    }
    body = "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items()
    )
    return f"---\n{body}\n---"


def _wikilinks(note_id: str, links: tuple[Edge, ...]) -> list[str]:
    return [
        f"- {edge.kind.value} [[{edge.target_id}]]" for edge in links if edge.source_id == note_id
    ]


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
