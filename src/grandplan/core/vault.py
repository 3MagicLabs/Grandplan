"""MarkdownVaultWriter — renders an approved note as Obsidian-friendly Markdown.

Output: YAML frontmatter (JSON-encoded values, so titles/tags are always valid YAML and
dependency-free), a title heading, the organized body, typed `[[wikilinks]]`, and a **verbatim**
"Source (original)" block in a dynamically-sized code fence so any backticks in the original
cannot break it. The verbatim original keeps the note lossless on disk too.

File naming & links: files are named after a **clean, human-readable slug** of the title — the
content id is *not* in the filename (it lives in frontmatter `id` + `aliases`). Links render as
`[[<target-filename>|<title>]]` — the target's actual slug — which Obsidian resolves **natively**
(no id indirection) and survives plain-Markdown export. (Linking by id instead produces a phantom
id-named node in the graph and breaks on export — the SiYuan failure mode.) The `aliases: ["<id>"]`
entry is kept only as a fallback so any *legacy* `[[<id>]]` links still resolve. If two *different*
notes slugify to the same name, the second is disambiguated (`<slug>-<id6>.md`) so a note is never
clobbered; the per-projection stems map (see `plan_filenames`) keeps links and filenames in sync.
The `source` object is flattened into scalar `source_*` keys so Obsidian's property UI renders it
cleanly. Planning properties (`due`, `contexts`, `collections`) are emitted when present.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from grandplan.core.fs import write_text_if_changed
from grandplan.core.models import Edge, Note, NoteEvent, NoteStatus, Original
from grandplan.core.resources import Resource, ResourceKind

_SLUG = re.compile(r"[^0-9a-z]+")
# Obsidian tag charset: letters, digits, '_', '-', '/'. Everything else is collapsed to '-'.
_TAG_INVALID = re.compile(r"[^0-9a-z/_-]+")
_ID_LINE = re.compile(r'^id:\s*"([^"]+)"', re.MULTILINE)


def note_filename(note: Note) -> str:
    """Clean, human-readable file stem for a note (the id lives in frontmatter/aliases, not here)."""
    return _slug(note.title)


def plan_filenames(notes: Iterable[Note]) -> dict[str, str]:
    """Deterministic `id → filename-stem` map for a set of notes.

    Filenames are a pure function of the note set (not of disk state), so a note's links and its own
    file always agree on the same stem — the key to resolvable `[[filename]]` links. Two notes that
    slugify to the same base are disambiguated with a short id suffix; iteration is id-sorted so the
    assignment is stable across runs (the first id wins the clean slug).
    """
    stems: dict[str, str] = {}
    owner: dict[str, str] = {}  # stem -> id of the note that already owns it
    for note in sorted(notes, key=lambda n: n.id):
        base = note_filename(note)
        stem = base if owner.get(base, note.id) == note.id else f"{base}-{note.id[:6]}"
        owner[stem] = note.id
        stems[note.id] = stem
    return stems


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
        preserve_body: bool = False,
        stems: Mapping[str, str] | None = None,
        backlinks: tuple[Edge, ...] = (),
        sources: Mapping[str, Note] | None = None,
    ) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        # Prefer the projection-wide stems map (keeps this file's name and its inbound links in sync,
        # incl. collision suffixes); fall back to disk-based disambiguation for one-off incremental writes.
        stem = (stems or {}).get(note.id) or self._unique_stem(note)
        path = self._dir / f"{stem}.md"
        # Ownership split (option B): grandplan owns the frontmatter / Links / History / Source blocks;
        # the BODY belongs to whoever edits the file (the user or another AI). On a re-render we keep
        # the on-disk body so an external edit is never clobbered; a fresh note (or a re-organize that
        # opts out) uses the note's own body.
        body_override = extract_body(path) if preserve_body and path.exists() else None
        markdown = render_markdown(
            note,
            original,
            links,
            targets=targets,
            status=status,
            history=history,
            body_override=body_override,
            stems=stems,
            backlinks=backlinks,
            sources=sources,
        )
        # Skip the write when the re-rendered file is byte-identical to what's on disk (audit P1.1):
        # a projection re-renders every note each capture, but only a few actually change. Skipping
        # keeps mtimes stable so a cloud-synced vault doesn't re-upload everything. `path` is still
        # returned (the note IS "written" for the caller's rename-sweep), whether or not bytes moved.
        write_text_if_changed(path, markdown)
        return path

    def _unique_stem(self, note: Note) -> str:
        """A clean slug stem, disambiguated only if a *different* note already owns that name."""
        base = note_filename(note)
        existing = self._dir / f"{base}.md"
        if not existing.exists() or _file_note_id(existing) == note.id:
            return base  # free, or the same note being rewritten (idempotent)
        return f"{base}-{note.id[:6]}"  # a different note has this slug → never clobber it


# The grandplan-managed section headings, in render order. Everything BEFORE the first of these
# (after the `# title`) is the agent/user-owned body; these blocks are always regenerated.
_MANAGED_HEADINGS: tuple[str, ...] = (
    "## Links",
    "## Linked mentions",
    "## Resources",
    "## History",
    "## Source (original)",
)


def extract_body(path: Path) -> str | None:
    """The on-disk body of a note file: the text between the `# title` and the first managed section.

    Used to preserve an externally-edited body across re-renders (option B). Returns None if the file
    can't be read or has no recognisable structure (then the caller falls back to the note's body).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines()
    start = next((i + 1 for i, line in enumerate(lines) if line.startswith("# ")), None)
    if start is None:
        return None  # no H1 title → unrecognised; don't risk a wrong body
    end = next(
        (i for i in range(start, len(lines)) if lines[i].rstrip() in _MANAGED_HEADINGS), len(lines)
    )
    return "\n".join(lines[start:end]).strip()


def render_markdown(
    note: Note,
    original: Original,
    links: tuple[Edge, ...],
    *,
    targets: Mapping[str, Note] | None = None,
    status: NoteStatus | None = None,
    history: tuple[NoteEvent, ...] = (),
    body_override: str | None = None,
    stems: Mapping[str, str] | None = None,
    backlinks: tuple[Edge, ...] = (),
    sources: Mapping[str, Note] | None = None,
) -> str:
    body = (body_override if body_override is not None else note.body).strip()
    parts = [_frontmatter(note, original, status), "", f"# {note.title}", "", body]
    wikilinks = _wikilinks(note.id, links, targets or {}, stems)
    if wikilinks:
        parts += ["", "## Links", *wikilinks]
    mentions = _backlinks(note.id, backlinks, sources or {}, stems)
    if mentions:
        parts += ["", "## Linked mentions", *mentions]
    if note.resources:
        parts += ["", "## Resources", "", *[_resource_line(r) for r in note.resources]]
    if history:
        parts += ["", "## History", "", *_history_lines(history)]
    parts += ["", "## Source (original)", "", _fenced(original.text)]
    return "\n".join(parts) + "\n"


def _resource_line(resource: Resource) -> str:
    """Render a resource WITHOUT ever creating an Obsidian graph node.

    The trap: a Markdown link to a *relative path* — `[x](path/to/key_points.docx)` — is still an
    INTERNAL link to Obsidian, so it spawns an unresolved phantom node (and a `path/to/…` tree in the
    file list). Only an http(s) URL is treated as external (no node). So: URLs render as clickable
    links/embeds; local file paths render as **inline code** — visible, copyable, but never a link
    and never a node. Placeholders are plain text. (Wikilinks are never used for resources at all.)
    """
    ref = resource.ref
    if resource.kind is ResourceKind.PLACEHOLDER:
        return f"- ⬜ {ref} _(placeholder — to be attached)_"
    if ref.startswith(("http://", "https://")):  # external URL — safe to link/embed, no graph node
        if resource.kind is ResourceKind.IMAGE:
            return f"- ![{resource.label or 'image'}]({ref})"
        return f"- [{resource.label or ref}]({ref})"
    # a local file path → inline code, never an internal link, so Obsidian adds no phantom node
    label = f"{resource.label}: " if resource.label else ""
    return f"- {label}`{ref}`"


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


def _wikilinks(
    note_id: str,
    links: tuple[Edge, ...],
    targets: Mapping[str, Note],
    stems: Mapping[str, str] | None = None,
) -> list[str]:
    rendered: list[str] = []
    for edge in links:
        if edge.source_id != note_id:
            continue
        target = targets.get(edge.target_id)
        # Skip a link whose target note isn't known: any `[[…]]` to a non-existent note renders as a
        # phantom node in Obsidian. Better no link than a broken one.
        if target is None:
            continue
        # Link by the target's human-readable FILENAME — Obsidian resolves `[[filename]]` natively and
        # the link survives plain-Markdown export. NEVER the opaque id (it becomes a phantom id-named
        # node and dies on export — the reported bug). The stems map gives the exact on-disk stem incl.
        # any collision suffix; without it, the plain title slug is correct in the no-collision case.
        stem = (stems or {}).get(edge.target_id) or note_filename(target)
        rendered.append(f"- {edge.kind.value} [[{stem}|{target.title}]]")
    return rendered


def _backlinks(
    note_id: str,
    backlinks: tuple[Edge, ...],
    sources: Mapping[str, Note],
    stems: Mapping[str, str] | None = None,
) -> list[str]:
    """Inbound links: the notes that link TO this one, rendered by the SOURCE note's filename.

    The portable, plain-Markdown counterpart to Obsidian's backlinks pane — same filename-not-id rule
    as outbound links (a backlink whose source note is unknown is dropped, never a phantom)."""
    rendered: list[str] = []
    for edge in backlinks:
        if edge.target_id != note_id:
            continue
        source = sources.get(edge.source_id)
        if source is None:
            continue
        stem = (stems or {}).get(edge.source_id) or note_filename(source)
        rendered.append(f"- {edge.kind.value} [[{stem}|{source.title}]]")
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
    """The `id` recorded in a note file's frontmatter, if any (for collision / orphan / delete checks).

    Reads only the frontmatter HEAD, not the whole file (audit P1.3): the id lives in the first few
    lines, so slurping a large note's entire body just to read its id wasted I/O on every deletion
    scan (which reads every `.md` in the vault). A missing/unreadable/non-text head yields None —
    treated as "not a grandplan note", never a crash of the projection."""
    try:
        with path.open("rb") as handle:
            head_bytes = handle.read(512)  # only the first 512 BYTES leave the disk — not the body
    except OSError:  # missing / unreadable
        return None
    head = head_bytes.decode(
        "utf-8", errors="ignore"
    )  # lenient: a garbled head can't crash the scan
    match = _ID_LINE.search(head)
    return match.group(1) if match else None
