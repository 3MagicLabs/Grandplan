"""Vault projections — regenerate the derived views (graph.json + Plan.md) from the graph.

A note's truth lives in the graph (notes + typed edges); the JSON graph and the actionable
`Plan.md` (with its Mermaid diagram) are pure projections of it (SPEC §11 "one source, three
views"). Both the CLI and the GUI call this after a write so the plan stays current — the
"grand plan" materializes as notes are captured.

Safety (writing into a real Obsidian vault): these are *generated* files, regenerated on every
save. If a file named `Plan.md` / `graph.json` already exists and was **not** produced by
grandplan (e.g. the user's own hand-written plan), it is **never overwritten** — grandplan diverts
its output to a `<stem>.grandplan.<ext>` sibling and logs a warning, so no user data is clobbered.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

from grandplan.core.graph import export_graph
from grandplan.core.models import Edge, Note
from grandplan.core.planner import (
    _MASTERPLAN_MARKER,
    _TIMELINE_MARKER,
    write_masterplan,
    write_plan,
    write_timeline,
)
from grandplan.core.ports import NoteRepository
from grandplan.core.store import OriginalStore
from grandplan.core.vault import MarkdownVaultWriter, read_note_id

logger = logging.getLogger(__name__)

# A marker line render_plan() always emits, used to recognise a grandplan-generated Plan.md.
_PLAN_MARKER = "Generated projection of the knowledge graph"

# Distinct Obsidian graph-node colours per note type, so the graph isn't one undifferentiated
# colour. Keyed on the `type/<type>` tag the vault writer emits. RGB packed as Obsidian expects.
_TYPE_COLORS: dict[str, int] = {
    "goal": 0x9C27B0,  # purple
    "project": 0x2196F3,  # blue
    "task": 0x4CAF50,  # green
    "decision": 0xFF9800,  # orange
    "question": 0xF44336,  # red
    "reference": 0x009688,  # teal
    "entity": 0xE91E63,  # pink
    "idea": 0x9E9E9E,  # grey
}


# Generated MOC / guide files are clutter in the *meaning* graph (they're views, not knowledge), so
# the default Obsidian graph filter hides them — leaving only real notes and their typed connections.
_GENERATED_FILES = ("Plan.md", "Masterplan.md", "Timeline.md", "graph.json", "_grandplan-guide.md")
_GRAPH_FILTER = " ".join(f'-path:"{name}"' for name in _GENERATED_FILES)


def write_obsidian_config(vault_dir: Path) -> Path | None:
    """Colour the graph by note type AND hide generated MOC files, via `.obsidian/graph.json`.

    Colour-by-type makes each node's KIND legible at a glance (goal/project/task/idea/…); the search
    filter removes the generated views so the graph shows only real notes and their true connections.
    Non-destructive: only fills in `colorGroups` / `search` when the user hasn't set them — never
    overwrites their choices.
    """
    config = vault_dir / ".obsidian" / "graph.json"
    groups = [
        {"query": f"tag:#type/{note_type}", "color": {"a": 1, "rgb": rgb}}
        for note_type, rgb in _TYPE_COLORS.items()
    ]
    if config.exists():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # unreadable/foreign config → leave it alone
        if not isinstance(data, dict):
            return None
        changed = False
        if not data.get("colorGroups"):
            data["colorGroups"] = groups  # fill empty/missing groups, keep everything else
            changed = True
        if not data.get("search"):
            data["search"] = _GRAPH_FILTER  # hide generated files, respect a user-set filter
            changed = True
        if not changed:
            return None  # the user already configured both → respect them
        config.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return config
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps({"colorGroups": groups, "search": _GRAPH_FILTER}, indent=2), encoding="utf-8"
    )
    return config


_GUIDE_MARKER = "grandplan vault guide"
_GUIDE = f"""# How this vault is organised

> {_GUIDE_MARKER} — for you (or another AI) reading and editing these notes. The vault is plain
> Markdown, so any tool or agent has full read/write access. Edit notes freely.

**Ownership:** you own each note's **body**; grandplan owns the frontmatter / `## Links` / `## History`
/ `## Source (original)` blocks. grandplan regenerates those on each save but **never clobbers your
body text** — so another AI can rewrite a note's body and the edit survives.

## Note anatomy
- `---` frontmatter: `id` (stable identifier — do not change), `type`
  (idea|reference|task|project|goal|decision|question|entity), `status`
  (inbox|next|active|done|needs-review|superseded), `horizon` (masterplan|goal|project|action),
  `tags` (includes structural `type/…`, `status/…`, `horizon/…` used to colour the graph), optional
  `due`, `resources`.
- `# Title`, then the body: a one-line summary, key points, and — for actionable notes — a
  `## Next steps` section of `- [ ]` checklist items.
- `## Links`: typed relationships as `[[id|title]]`. `## History`: the note's change log.
  `## Source (original)`: the verbatim capture — never edit this.

## How to relate notes (another AI)
Add a typed link line under `## Links`, e.g. `- depends_on [[<id>|<title>]]`. Edge kinds:
`depends_on`, `blocks`, `waiting_on`, `part_of`, `next`, `relates`, `builds_on`, `refines`,
`supersedes`, `contradicts`, `involves`. These edges drive the plan, timeline, and graph.

## Generated views (don't hand-edit — they are projections of the notes)
`Plan.md` (now/blocked), `Timeline.md` (feasible schedule), `Masterplan.md` (by horizon),
`graph.json` (nodes + typed edges). They are hidden from the Obsidian graph so it shows only real
notes and their true connections.
"""


def write_guide(vault_dir: Path) -> Path:
    """Write the agent/human guide describing the vault's conventions (foreign file preserved)."""
    path = _safe_target(vault_dir / "_grandplan-guide.md", _is_grandplan_guide)
    path.write_text(_GUIDE, encoding="utf-8")
    return path


def _is_grandplan_guide(path: Path) -> bool:
    try:
        return _GUIDE_MARKER in path.read_text(encoding="utf-8")[:2048]
    except OSError:
        return False


# A bare note-id filename (`<16-hex>.md`) — what Obsidian creates as an empty stub when a user
# clicks an unresolved `[[id]]` link. We resolve links now, so these are leftover clutter.
_PHANTOM_NOTE = re.compile(r"^[0-9a-f]{16}\.md$")


def remove_phantom_link_files(vault_dir: Path) -> int:
    """Delete EMPTY `<id>.md` stubs Obsidian created from old phantom `[[id]]` links. Safe: only a
    bare-id filename, no grandplan frontmatter, and empty content — never a real note or user file."""
    removed = 0
    for md in vault_dir.glob("*.md"):
        if not _PHANTOM_NOTE.match(md.name) or read_note_id(md) is not None:
            continue
        try:
            empty = not md.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        if empty:
            md.unlink()
            removed += 1
    return removed


def write_projections(
    repo: NoteRepository,
    vault_dir: Path,
    *,
    originals: OriginalStore | None = None,
    preserve_external_body: bool = True,
    reconcile_deletions: bool = False,
    protect_ids: frozenset[str] = frozenset(),
) -> tuple[Path, Path]:
    """Write `graph.json` + `Plan.md` into `vault_dir`; return their paths. Idempotent.

    Foreign same-named files are preserved (output is diverted to a `.grandplan` sibling). When
    `originals` is supplied, each note's `.md` is also **re-rendered from its derived state**
    (PR-C) — derived status + edited fields + per-note history — so the vault reflects progress;
    omit it to keep the lighter graph+plan-only behaviour. `preserve_external_body` (option B) keeps
    a note's on-disk body across re-renders so another AI's edits aren't clobbered; pass False to
    re-organize from scratch (regenerate).
    """
    vault_dir.mkdir(parents=True, exist_ok=True)
    # Tombstone user-deleted notes FIRST — before any projection is written — so the graph, Plan,
    # Masterplan and Timeline all reflect the deletions (otherwise they'd still list the removed
    # notes, having been written from the pre-tombstone state).
    if reconcile_deletions and originals is not None:
        _tombstone_user_deletions(repo, originals, vault_dir, protect_ids)
    write_obsidian_config(
        vault_dir
    )  # colour the graph by type + hide generated files (non-destructive)
    write_guide(vault_dir)  # the agent/human guide to the vault's conventions
    remove_phantom_link_files(vault_dir)  # sweep empty `<id>.md` stubs from old phantom links
    graph_path = export_graph(repo, _safe_target(vault_dir / "graph.json", _is_grandplan_graph))
    plan_path = write_plan(repo, _safe_target(vault_dir / "Plan.md", _is_grandplan_plan))
    # The Masterplan MOC (notes stratified by horizon); foreign same-named file is preserved.
    write_masterplan(repo, _safe_target(vault_dir / "Masterplan.md", _is_grandplan_masterplan))
    # The Timeline (feasible execution order from the dependency DAG + due dates).
    write_timeline(repo, _safe_target(vault_dir / "Timeline.md", _is_grandplan_timeline))
    if originals is not None:
        write_notes(repo, originals, vault_dir, preserve_external_body=preserve_external_body)
    return graph_path, plan_path


def write_notes(
    repo: NoteRepository,
    originals: OriginalStore,
    vault_dir: Path,
    *,
    preserve_external_body: bool = True,
) -> tuple[Path, ...]:
    """Re-render every note's `.md` from its *derived* state (PR-C); return the paths written.

    Each file shows the current (edited) fields, derived status, and a `## History` section. A note
    is skipped if its verbatim `Original` is missing (we never write a lossy note). After writing,
    a sweep removes any prior `.md` whose frontmatter `id` belongs to a re-rendered note but sits at
    a different path (a stale file left when a title edit changed the slug) — foreign files (no
    matching id: `Plan.md`, hand-written notes) are never touched. Deletion reconciliation happens in
    `write_projections` (before the projections), so by here a deleted note is already tombstoned.
    """
    writer = MarkdownVaultWriter(vault_dir)
    current = repo.current_notes()
    by_id = {note.id: note for note in current}
    edges_by_source: dict[str, list[Edge]] = {}
    for edge in repo.edges():
        edges_by_source.setdefault(edge.source_id, []).append(edge)

    written: dict[str, Path] = {}
    for note in current:
        original = originals.get(note.original_id)
        if original is None:
            logger.warning("note %s has no stored original; skipping re-render", note.id)
            continue
        links = tuple(edges_by_source.get(note.id, ()))
        targets: dict[str, Note] = {
            edge.target_id: by_id[edge.target_id] for edge in links if edge.target_id in by_id
        }
        # `note` is already the derived current note (its `.status` is the derived status), so the
        # writer's default `status=None` correctly renders the current status — no override needed.
        written[note.id] = writer.write(
            note,
            original,
            links,
            targets=targets,
            history=repo.history_of(note.id),
            preserve_body=preserve_external_body,
        )
    _remove_renamed_orphans(vault_dir, written)
    return tuple(written.values())


def _tombstone_user_deletions(
    repo: NoteRepository,
    originals: OriginalStore,
    vault_dir: Path,
    protect_ids: frozenset[str],
) -> None:
    """Record a delete event for any note whose `.md` the user removed (so it isn't re-created).

    A note counts as deleted when it is still in the index, has a stored Original (so it *could* be on
    disk), its file is absent from the vault, and it isn't protected (just committed). Append-only.
    """
    present: set[str | None] = {read_note_id(md) for md in vault_dir.glob("*.md")}
    for note in repo.current_notes():
        if (
            note.id not in present
            and note.id not in protect_ids
            and originals.get(note.original_id) is not None
        ):
            repo.delete_note(note.id)


def _remove_renamed_orphans(vault_dir: Path, written: dict[str, Path]) -> None:
    """Delete only stale files of notes we just re-rendered under a new (title-derived) name."""
    kept = set(written.values())
    rendered_ids = set(written)
    # Flat glob: MarkdownVaultWriter writes every note directly into `vault_dir` (no subdirectories),
    # so a non-recursive sweep covers all note files. A file is removed ONLY when its frontmatter id
    # belongs to a note we just re-rendered at a different path — never a foreign/hand-written file.
    for md in vault_dir.glob("*.md"):
        if md in kept:
            continue
        if read_note_id(md) in rendered_ids:  # same note, different path → a stale rename
            md.unlink()


_MAX_DIVERT_DEPTH = (
    20  # absurdly many foreign same-named files → bail loudly, never loop/blow stack
)


def _safe_target(path: Path, is_ours: Callable[[Path], bool], _depth: int = 0) -> Path:
    """The path to write — diverted to a `.grandplan` sibling if a foreign file occupies it.

    Recurses so a chain of foreign files (e.g. both `Plan.md` and `Plan.grandplan.md` are the
    user's) is never clobbered; it terminates at the first free or grandplan-owned slot. A depth
    guard prevents unbounded recursion if every candidate is somehow foreign (robustness).
    """
    if not path.exists() or is_ours(path):
        return path
    if _depth >= _MAX_DIVERT_DEPTH:
        raise RuntimeError(
            f"too many conflicting files near {path.name}; cannot find a safe target"
        )
    diverted = path.with_name(f"{path.stem}.grandplan{path.suffix}")
    logger.warning(
        "%s exists and was not generated by grandplan; writing %s instead so your file is kept",
        path.name,
        diverted.name,
    )
    return _safe_target(diverted, is_ours, _depth + 1)


def _is_grandplan_plan(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8")[:2048]
    except OSError:
        return False
    return _PLAN_MARKER in head


def _is_grandplan_masterplan(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8")[:2048]
    except OSError:
        return False
    return _MASTERPLAN_MARKER in head


def _is_grandplan_timeline(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8")[:2048]
    except OSError:
        return False
    return _TIMELINE_MARKER in head


def _is_grandplan_graph(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    # The `_grandplan` sentinel distinguishes our export from any other tool's {nodes,edges} JSON
    # (D3/networkx/Cytoscape all use that shape), so we never overwrite a foreign graph export.
    return isinstance(data, dict) and data.get("_grandplan") is True
