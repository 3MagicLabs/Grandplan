"""Planner — project the note graph into an actionable plan (US-8, SPEC §11).

The plan is a *projection*, never hand-maintained: a `part_of` hierarchy, a topological order
over the `depends_on`/`blocks` dependency DAG, a "now" list of unblocked actionable notes, and
a blocked list with reasons. Dependency cycles are detected and surfaced rather than crashing.
Pure core — no IO except `write_plan`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from grandplan.core.models import EdgeKind, Horizon, Note, NoteStatus, NoteType
from grandplan.core.ports import NoteRepository

_HORIZON_RANK: dict[Horizon, int] = {
    Horizon.MASTERPLAN: 0,
    Horizon.GOAL: 1,
    Horizon.PROJECT: 2,
    Horizon.ACTION: 3,
}


@dataclass(frozen=True)
class PlanItem:
    """A blocked actionable note and the (incomplete) notes blocking it."""

    note: Note
    blocked_by: tuple[Note, ...]


@dataclass(frozen=True)
class Plan:
    """A projection of the graph: now / blocked / dependency order / hierarchy / cycles."""

    now: tuple[Note, ...]
    blocked: tuple[PlanItem, ...]
    ordered: tuple[Note, ...]
    cycle: tuple[Note, ...]
    root_ids: tuple[str, ...]
    by_id: dict[str, Note]
    child_ids: dict[str, tuple[str, ...]]
    deps: dict[str, tuple[str, ...]]  # note id -> its prerequisite note ids (depends_on/blocks)
    related: tuple[tuple[str, str], ...]  # semantic (relates) links, as (source, target) pairs


def build_plan(repo: NoteRepository) -> Plan:
    notes = {note.id: note for note in repo.notes()}
    deps = _dependencies(repo, notes)
    order_ids, cycle_ids = _toposort(notes, deps)
    done = {nid for nid, note in notes.items() if note.status is NoteStatus.DONE}

    now: list[Note] = []
    blocked: list[PlanItem] = []
    for nid in order_ids:
        note = notes[nid]
        if not _actionable(note):
            continue
        incomplete = tuple(notes[p] for p in sorted(deps[nid]) if p not in done)
        if incomplete:
            blocked.append(PlanItem(note=note, blocked_by=incomplete))
        else:
            now.append(note)

    parent_of, child_ids = _hierarchy(repo, notes)
    root_ids = tuple(
        sorted(
            (nid for nid in notes if nid not in parent_of),
            key=lambda i: (_HORIZON_RANK[notes[i].horizon], notes[i].title, i),
        )
    )
    return Plan(
        now=tuple(now),
        blocked=tuple(blocked),
        ordered=tuple(notes[i] for i in order_ids),
        cycle=tuple(notes[i] for i in cycle_ids),
        root_ids=root_ids,
        by_id=notes,
        child_ids=child_ids,
        deps={nid: tuple(sorted(prereqs)) for nid, prereqs in deps.items()},
        related=_related(repo, notes),
    )


def _related(repo: NoteRepository, notes: dict[str, Note]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (edge.source_id, edge.target_id)
        for edge in repo.edges()
        if edge.kind is EdgeKind.RELATES and edge.source_id in notes and edge.target_id in notes
    )


def render_plan(plan: Plan) -> str:
    lines = [
        "# Plan",
        "",
        "> Generated projection of the knowledge graph — edit the notes, not this file.",
        "",
        "## Now",
        "",
    ]
    lines += (
        [f"- [ ] {note.title}  ^{note.id}" for note in plan.now]
        if plan.now
        else ["_Nothing actionable and unblocked._"]
    )
    lines += ["", "## Blocked", ""]
    if plan.blocked:
        for item in plan.blocked:
            blockers = ", ".join(b.title for b in item.blocked_by)
            lines.append(f"- {item.note.title} — blocked by: {blockers}")
    else:
        lines.append("_Nothing blocked._")
    lines += ["", "## By goal / project", ""]
    for root_id in plan.root_ids:
        lines += _render_tree(plan, root_id, 0)
    diagram = _mermaid(plan)
    if diagram:
        lines += ["", "## Map (diagram)", "", *diagram]
    if plan.cycle:
        lines += ["", "## ⚠ Dependency cycle", ""]
        lines += [f"- {note.title} (^{note.id})" for note in plan.cycle]
    return "\n".join(lines) + "\n"


def _mermaid(plan: Plan) -> list[str]:
    """An Obsidian-rendered Mermaid flowchart of the graph: dependencies + part-of hierarchy."""
    if not plan.by_id:
        return []
    lines = ["```mermaid", "graph TD"]
    for nid in sorted(plan.by_id):
        lines.append(f'    n{nid}["{_mermaid_label(plan.by_id[nid].title)}"]')
    for nid in sorted(plan.deps):
        for prereq in plan.deps[nid]:  # prerequisite --> dependent (completion flow)
            lines.append(f"    n{prereq} --> n{nid}")
    for parent in sorted(plan.child_ids):
        for child in plan.child_ids[parent]:
            lines.append(f"    n{child} -.->|part of| n{parent}")
    for src, tgt in plan.related:
        lines.append(f"    n{src} -.->|related| n{tgt}")
    lines.append("```")
    return lines


def _mermaid_label(title: str) -> str:
    """Neutralize characters that would break a Mermaid node label."""
    return title.replace('"', "'").replace("[", "(").replace("]", ")").replace("\n", " ")


def write_plan(repo: NoteRepository, path: Path) -> Path:
    path.write_text(render_plan(build_plan(repo)), encoding="utf-8")
    return path


def _actionable(note: Note) -> bool:
    return note.type is NoteType.TASK and note.status not in {
        NoteStatus.DONE,
        NoteStatus.SUPERSEDED,
    }


def _dependencies(repo: NoteRepository, notes: dict[str, Note]) -> dict[str, set[str]]:
    deps: dict[str, set[str]] = {nid: set() for nid in notes}
    for edge in repo.edges():
        if edge.source_id not in notes or edge.target_id not in notes:
            continue
        if edge.kind is EdgeKind.DEPENDS_ON:
            deps[edge.source_id].add(edge.target_id)
        elif edge.kind is EdgeKind.BLOCKS:
            deps[edge.target_id].add(edge.source_id)
    return deps


def _toposort(notes: dict[str, Note], deps: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    indegree = {nid: len(deps[nid]) for nid in notes}
    dependents: dict[str, list[str]] = {nid: [] for nid in notes}
    for nid in notes:
        for prereq in deps[nid]:
            dependents[prereq].append(nid)

    queue = sorted(nid for nid in notes if indegree[nid] == 0)
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        newly_ready = []
        for dependent in dependents[current]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                newly_ready.append(dependent)
        queue = sorted(queue + newly_ready)

    cycle = sorted(nid for nid in notes if indegree[nid] > 0)
    return order, cycle


def _hierarchy(
    repo: NoteRepository, notes: dict[str, Note]
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    parent_of: dict[str, str] = {}
    children: dict[str, list[str]] = {nid: [] for nid in notes}
    for edge in repo.edges():
        if edge.kind is not EdgeKind.PART_OF:
            continue
        if edge.source_id not in notes or edge.target_id not in notes:
            continue
        if edge.source_id not in parent_of:  # first parent wins
            parent_of[edge.source_id] = edge.target_id
            children[edge.target_id].append(edge.source_id)
    child_ids = {
        pid: tuple(sorted(kids, key=lambda i: (notes[i].title, i)))
        for pid, kids in children.items()
    }
    return parent_of, child_ids


def _render_tree(plan: Plan, nid: str, depth: int) -> list[str]:
    note = plan.by_id[nid]
    indent = "  " * depth
    if note.type is NoteType.TASK:
        box = "[x] " if note.status is NoteStatus.DONE else "[ ] "
    else:
        box = ""
    out = [f"{indent}- {box}{note.title} _({note.type.value}/{note.horizon.value})_"]
    for child in plan.child_ids.get(nid, ()):
        out += _render_tree(plan, child, depth + 1)
    return out
