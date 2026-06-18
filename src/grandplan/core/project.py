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
from collections.abc import Callable
from pathlib import Path

from grandplan.core.graph import export_graph
from grandplan.core.models import Edge, Note
from grandplan.core.planner import write_plan
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


def write_obsidian_config(vault_dir: Path) -> Path | None:
    """Write `.obsidian/graph.json` colouring graph nodes by note type — but NEVER clobber the
    user's own graph settings (write only if absent). Returns the path written, or None if skipped."""
    config = vault_dir / ".obsidian" / "graph.json"
    if config.exists():
        return None
    config.parent.mkdir(parents=True, exist_ok=True)
    groups = [
        {"query": f"tag:#type/{note_type}", "color": {"a": 1, "rgb": rgb}}
        for note_type, rgb in _TYPE_COLORS.items()
    ]
    config.write_text(json.dumps({"colorGroups": groups}, indent=2), encoding="utf-8")
    return config


def write_projections(
    repo: NoteRepository, vault_dir: Path, *, originals: OriginalStore | None = None
) -> tuple[Path, Path]:
    """Write `graph.json` + `Plan.md` into `vault_dir`; return their paths. Idempotent.

    Foreign same-named files are preserved (output is diverted to a `.grandplan` sibling). When
    `originals` is supplied, each note's `.md` is also **re-rendered from its derived state**
    (PR-C) — derived status + edited fields + per-note history — so the vault reflects progress;
    omit it to keep the lighter graph+plan-only behaviour.
    """
    vault_dir.mkdir(parents=True, exist_ok=True)
    write_obsidian_config(vault_dir)  # colour the graph by type (non-destructive)
    graph_path = export_graph(repo, _safe_target(vault_dir / "graph.json", _is_grandplan_graph))
    plan_path = write_plan(repo, _safe_target(vault_dir / "Plan.md", _is_grandplan_plan))
    if originals is not None:
        write_notes(repo, originals, vault_dir)
    return graph_path, plan_path


def write_notes(
    repo: NoteRepository, originals: OriginalStore, vault_dir: Path
) -> tuple[Path, ...]:
    """Re-render every note's `.md` from its *derived* state (PR-C); return the paths written.

    Each file shows the current (edited) fields, derived status, and a `## History` section. A note
    is skipped if its verbatim `Original` is missing (we never write a lossy note). After writing,
    a sweep removes any prior `.md` whose frontmatter `id` belongs to a re-rendered note but sits at
    a different path (a stale file left when a title edit changed the slug) — foreign files (no
    matching id: `Plan.md`, hand-written notes) are never touched.
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
            note, original, links, targets=targets, history=repo.history_of(note.id)
        )
    _remove_renamed_orphans(vault_dir, written)
    return tuple(written.values())


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


def _safe_target(path: Path, is_ours: Callable[[Path], bool]) -> Path:
    """The path to write — diverted to a `.grandplan` sibling if a foreign file occupies it.

    Recurses so a chain of foreign files (e.g. both `Plan.md` and `Plan.grandplan.md` are the
    user's) is never clobbered; it terminates at the first free or grandplan-owned slot.
    """
    if not path.exists() or is_ours(path):
        return path
    diverted = path.with_name(f"{path.stem}.grandplan{path.suffix}")
    logger.warning(
        "%s exists and was not generated by grandplan; writing %s instead so your file is kept",
        path.name,
        diverted.name,
    )
    return _safe_target(diverted, is_ours)


def _is_grandplan_plan(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8")[:2048]
    except OSError:
        return False
    return _PLAN_MARKER in head


def _is_grandplan_graph(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    # The `_grandplan` sentinel distinguishes our export from any other tool's {nodes,edges} JSON
    # (D3/networkx/Cytoscape all use that shape), so we never overwrite a foreign graph export.
    return isinstance(data, dict) and data.get("_grandplan") is True
