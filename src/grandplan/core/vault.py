"""MarkdownVaultWriter — renders an approved note as Obsidian-friendly Markdown.

Output: YAML frontmatter (JSON-encoded values, so titles/tags are always valid YAML and
dependency-free), a title heading, the organized body, typed `[[wikilinks]]`, and a **verbatim**
"Source (original)" block in a dynamically-sized code fence so any backticks in the original
cannot break it. The verbatim original keeps the note lossless on disk too.

File naming & links: files are named after a **clean, human-readable slug** of the title — the
content id is *not* in the filename (it lives in frontmatter `id` + `aliases`). Links render as
`[[<id>|<title>]]`, which Obsidian resolves to the target via its `aliases: ["<id>"]` and displays
the title — so links are independent of the (clean) filename. If two *different* notes slugify to
the same name, the second is disambiguated (`<slug>-<id6>.md`) so a note is never clobbered.
The `source` object is flattened into scalar `source_*` keys so Obsidian's property UI renders it
cleanly. Planning properties (`due`, `contexts`, `collections`) are emitted when present.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from grandplan.core.models import Edge, Note, NoteEvent, NoteStatus, Original
from grandplan.core.resources import Resource, ResourceKind

_SLUG = re.compile(r"[^0-9a-z]+")
# Obsidian tag charset: letters, digits, '_', '-', '/'. Everything else is collapsed to '-'.
_TAG_INVALID = re.compile(r"[^0-9a-z/_-]+")
_ID_LINE = re.compile(r'^id:\s*"([^"]+)"', re.MULTILINE)


def note_filename(note: Note) -> str:
    """Clean, human-readable file stem for a note (the id lives in frontmatter/aliases, not here)."""
    return _slug(note.title)


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
        status: NoteStatus | None = None,
        history: tuple[NoteEvent, ...] = (),
    ) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{self._unique_stem(note)}.md"
        markdown = render_markdown(
            note, original, links, targets=targets, status=status, history=history
        )
        path.write_text(markdown, encoding="utf-8")
        return path

    def _unique_stem(self, note: Note) -> str:
        """A clean slug stem, disambiguated only if a *different* note already owns that name."""
        base = note_filename(note)
        existing = self._dir / f"{base}.md"
        if not existing.exists() or _file_note_id(existing) == note.id:
            return base  # free, or the same note being rewritten (idempotent)
        return f"{base}-{note.id[:6]}"  # a different note has this slug → never clobber it


def render_markdown(
    note: Note,
    original: Original,
    links: tuple[Edge, ...],
    *,
    targets: Mapping[str, Note] | None = None,
    status: NoteStatus | None = None,
    history: tuple[NoteEvent, ...] = (),
) -> str:
    parts = [_frontmatter(note, original, status), "", f"# {note.title}", "", note.body.strip()]
    wikilinks = _wikilinks(note.id, links, targets or {})
    if wikilinks:
        parts += ["", "## Links", *wikilinks]
    if note.resources:
        parts += ["", "## Resources", "", *[_resource_line(r) for r in note.resources]]
    if history:
        parts += ["", "## History", "", *_history_lines(history)]
    parts += ["", "## Source (original)", "", _fenced(original.text)]
    return "\n".join(parts) + "\n"


def _resource_line(resource: Resource) -> str:
    """Render a resource as native Obsidian: a link/embed for URLs, a wikilink/embed for files."""
    ref = resource.ref
    if resource.kind is ResourceKind.PLACEHOLDER:
        return f"- ⬜ {ref} _(placeholder — to be attached)_"
    is_url = ref.startswith(("http://", "https://"))
    if resource.kind is ResourceKind.IMAGE:
        return f"- ![{resource.label or 'image'}]({ref})" if is_url else f"- ![[{ref}]]"
    if resource.kind is ResourceKind.FILE and not is_url and "/" not in ref and "\\" not in ref:
        return f"- [[{ref}]]"  # a bare vault name resolves as a wikilink
    return f"- [{resource.label or ref}]({ref})"  # external link, or a file path as a markdown link


def _history_lines(history: tuple[NoteEvent, ...]) -> list[str]:
    """The note's "git log" — one bullet per event, newest last (append order)."""
    lines: list[str] = []
    for event in history:
        prefix = f"{event.at} · " if event.at else ""
        lines.append(f"- {prefix}{event.summary()}")
    return lines


def read_note_id(path: Path) -> str | None:
    """The `id` recorded in a note file's frontmatter, if any (for re-render / orphan checks)."""
    return _file_note_id(path)


def _frontmatter(note: Note, original: Original, status: NoteStatus | None = None) -> str:
    # `status` is the derived current status (ADR-0008); it overrides the note's creation status
    # in the rendered frontmatter without mutating the note. None => use the note's own status.
    fields: dict[str, object] = {
        "id": note.id,
        "aliases": [note.id],  # so `[[<id>]]` links resolve to this file in Obsidian
        "type": note.type.value,
        "status": (status or note.status).value,
        "horizon": note.horizon.value,
    }
    # Planning properties — emitted only when set, to keep frontmatter uncluttered.
    if note.due is not None:
        fields["due"] = note.due
    # Structural tags (type/status/horizon) make the note queryable AND let the Obsidian graph
    # colour nodes by kind (see core.project.write_obsidian_config) — so the graph isn't all one
    # colour. Prepended to the user's topical tags; nested tags (`type/idea`) are valid in Obsidian.
    structural = [
        f"type/{note.type.value}",
        f"status/{(status or note.status).value}",
        f"horizon/{note.horizon.value}",
    ]
    fields["tags"] = structural + [t for t in _sanitize_tags(note.tags) if t not in structural]
    if note.contexts:
        fields["contexts"] = list(note.contexts)
    if note.collections:
        fields["collections"] = list(note.collections)
    # Concrete resource refs (not placeholders) → a queryable frontmatter list (PR-D).
    concrete = [r.ref for r in note.resources if r.kind is not ResourceKind.PLACEHOLDER]
    if concrete:
        fields["resources"] = concrete
    fields["created"] = original.created
    # Flattened so Obsidian's property editor shows clean scalars (not a raw JSON object).
    fields["source_app"] = original.source.app
    fields["source_title"] = original.source.title
    fields["source_uri"] = original.source.uri
    fields["original_id"] = original.id
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
        # Skip a link whose target note isn't known: a bare `[[<id>]]` can't resolve, so Obsidian
        # renders it as a phantom node *named by the id* — exactly the "ids as connected notes"
        # clutter. Better no link than a fake one. Resolved links use the target's `aliases:["<id>"]`
        # and display the title.
        if target is None:
            continue
        rendered.append(f"- {edge.kind.value} [[{edge.target_id}|{target.title}]]")
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


def _obsidian_tag(raw: str) -> str | None:
    """Coerce a raw tag into a valid Obsidian tag, or None if nothing usable remains."""
    tag = _TAG_INVALID.sub("-", raw.strip().lower())
    tag = re.sub(r"-{2,}", "-", tag).strip("-/_")
    if not tag or tag.isdigit():  # Obsidian rejects empty and purely-numeric tags
        return None
    return tag


def _sanitize_tags(tags: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for raw in tags:
        tag = _obsidian_tag(raw)
        if tag is not None and tag not in out:
            out.append(tag)
    return out


def _file_note_id(path: Path) -> str | None:
    """The `id` recorded in an existing note file's frontmatter, if any (for collision checks)."""
    try:
        head = path.read_text(encoding="utf-8")[:512]
    except OSError:
        return None
    match = _ID_LINE.search(head)
    return match.group(1) if match else None
