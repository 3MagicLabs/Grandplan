"""Planner — project the note graph into an actionable plan (US-8, SPEC §11).

The plan is a *projection*, never hand-maintained: a `part_of` hierarchy, a topological order
over the `depends_on`/`blocks` dependency DAG, a "now" list of unblocked actionable notes, and
a blocked list with reasons. Dependency cycles are detected and surfaced rather than crashing.
Pure core — no IO except `write_plan`.
"""

from __future__ import annotations

import heapq
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
    needs_review: tuple[Note, ...]  # contradictions / needs-review notes to resolve (US-10)
    contradictions: tuple[tuple[str, str], ...]  # contradicts edges, as (source, target) pairs
    status_by_id: dict[str, NoteStatus]  # derived current status per note (ADR-0008 event log)
    moved: tuple[str, ...]  # "what moved" digest lines, most-recent first (PR-C)


_MOVED_LIMIT = 10  # cap the "what moved" digest to the most recent N events


def build_plan(repo: NoteRepository) -> Plan:
    # Notes are the *derived* current notes (ADR-0008/PR-C): edited fields + status folded in from
    # the event log, so the plan agrees with the graph and the re-rendered note files.
    notes = {note.id: note for note in repo.current_notes()}
    # Current status is *derived* from the event log (ADR-0008), not read off the note: a `status`
    # event overrides the creation status without ever mutating the stored note. `status_of` always
    # returns a concrete status for an id in `notes` (it falls back to the note's creation status).
    status_by_id = {nid: repo.status_of(nid) or notes[nid].status for nid in notes}
    deps = _dependencies(repo, notes)
    order_ids, cycle_ids = _toposort(notes, deps)
    done = {nid for nid in notes if status_by_id[nid] is NoteStatus.DONE}
    # A note with an incoming `supersedes` edge is stale — excluded from the actionable plan, the
    # same effect as status SUPERSEDED but derived from the edge (no note is mutated; ADR-0007).
    superseded = _superseded_ids(repo, notes)

    now: list[Note] = []
    blocked: list[PlanItem] = []
    for nid in order_ids:
        note = notes[nid]
        if not _actionable(note, status_by_id[nid]) or nid in superseded:
            continue
        incomplete = tuple(notes[p] for p in sorted(deps[nid]) if p not in done)
        if incomplete:
            blocked.append(PlanItem(note=note, blocked_by=incomplete))
        else:
            now.append(note)

    parent_of, child_ids = _hierarchy(repo, notes)
    # `entity` notes are cross-cutting referents joined by `involves` edges, not part of the planning
    # hierarchy — keep them out of the masterplan roots so the plan stays goals/projects/actions.
    root_ids = tuple(
        sorted(
            (
                nid
                for nid in notes
                if nid not in parent_of and notes[nid].type is not NoteType.ENTITY
            ),
            key=lambda i: (_HORIZON_RANK[notes[i].horizon], notes[i].title, i),
        )
    )
    contradictions = _contradictions(repo, notes)
    flagged = {nid for nid in notes if status_by_id[nid] is NoteStatus.NEEDS_REVIEW}
    flagged |= {nid for pair in contradictions for nid in pair}
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
        needs_review=tuple(notes[i] for i in sorted(flagged)),
        contradictions=contradictions,
        status_by_id=status_by_id,
        moved=_what_moved(repo, notes),
    )


def _what_moved(repo: NoteRepository, notes: dict[str, Note]) -> tuple[str, ...]:
    """The most-recent events as digest lines (the "git for ideas" progress log, PR-C)."""
    lines: list[str] = []
    for event in reversed(repo.events()):  # global append order → most recent first
        note = notes.get(event.note_id)
        title = note.title if note is not None else event.note_id
        when = f" — {event.at}" if event.at else ""
        lines.append(f"{title}: {event.summary()}{when}")
        if len(lines) >= _MOVED_LIMIT:
            break
    return tuple(lines)


def _related(repo: NoteRepository, notes: dict[str, Note]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (edge.source_id, edge.target_id)
        for edge in repo.edges()
        if edge.kind is EdgeKind.RELATES and edge.source_id in notes and edge.target_id in notes
    )


def _superseded_ids(repo: NoteRepository, notes: dict[str, Note]) -> set[str]:
    """Notes made stale by an incoming `supersedes` edge (target = the superseded note)."""
    return {
        edge.target_id
        for edge in repo.edges()
        if edge.kind is EdgeKind.SUPERSEDES and edge.target_id in notes
    }


def _contradictions(repo: NoteRepository, notes: dict[str, Note]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (edge.source_id, edge.target_id)
        for edge in repo.edges()
        if edge.kind is EdgeKind.CONTRADICTS and edge.source_id in notes and edge.target_id in notes
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
    if plan.moved:
        lines += ["", "## What moved", ""]
        lines += [f"- {entry}" for entry in plan.moved]
    lines += ["", "## By goal / project", ""]
    for root_id in plan.root_ids:
        lines += _render_tree(plan, root_id, 0)
    if plan.needs_review:
        lines += ["", "## ⚠ Needs review", ""]
        lines += [f"- {note.title} (^{note.id})" for note in plan.needs_review]
        for src, tgt in plan.contradictions:
            a, b = plan.by_id.get(src), plan.by_id.get(tgt)
            if a is not None and b is not None:
                lines.append(f"  - contradiction: {a.title} ⟷ {b.title}")
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


# Horizon bands for the masterplan, top (long-term) → bottom (concrete), per SPEC §11.1.
_HORIZON_BANDS: tuple[tuple[Horizon, str], ...] = (
    (Horizon.MASTERPLAN, "Masterplan"),
    (Horizon.GOAL, "Goals"),
    (Horizon.PROJECT, "Projects"),
    (Horizon.ACTION, "Actions & ideas"),
)

_MASTERPLAN_MARKER = "Your knowledge organized by horizon"


def render_masterplan(plan: Plan) -> str:
    """A `Masterplan.md` MOC: top-level notes grouped by horizon (Goal/Project/Action), each with its
    `part_of` children nested beneath — the stratified view of the whole graph (SPEC §11.1)."""
    lines = [
        "# Masterplan",
        "",
        f"> {_MASTERPLAN_MARKER} — a projection of the graph (edit the notes, not this file).",
        "",
    ]
    roots_by_horizon: dict[Horizon, list[str]] = {}
    for (
        root_id
    ) in plan.root_ids:  # already sorted by (horizon, title, id); roots = no part_of parent
        roots_by_horizon.setdefault(plan.by_id[root_id].horizon, []).append(root_id)

    wrote_section = False
    for horizon, label in _HORIZON_BANDS:
        ids = roots_by_horizon.get(horizon, ())
        if not ids:
            continue
        wrote_section = True
        lines += [f"## {label}", ""]
        for root_id in ids:
            lines += _render_tree(plan, root_id, 0)
        lines.append("")
    if not wrote_section:
        lines += ["_No notes yet._", ""]
    return "\n".join(lines).rstrip() + "\n"


def write_masterplan(repo: NoteRepository, path: Path) -> Path:
    path.write_text(render_masterplan(build_plan(repo)), encoding="utf-8")
    return path


_TIMELINE_MARKER = "Feasible execution order"
_FAR_FUTURE = "~"  # sorts after any ISO date, so undated items fall to the end


@dataclass(frozen=True)
class Timeline:
    """A feasible execution schedule projected from the dependency DAG + due dates (PR: timeline).

    `ready` = actionable + unblocked (do these now); `waiting` = actionable + blocked, with what
    blocks them; `scheduled` = open actionable notes that carry a due date, in date order;
    `conflicts` = infeasibilities (a note due before its prerequisite, or a dependency cycle).
    """

    ready: tuple[Note, ...]
    waiting: tuple[PlanItem, ...]
    scheduled: tuple[Note, ...]
    conflicts: tuple[str, ...]


def _due_key(note: Note) -> tuple[str, str]:
    return (note.due or _FAR_FUTURE, note.title)


def build_timeline(repo: NoteRepository) -> Timeline:
    """Project the graph into a feasible timeline: ready / waiting / scheduled / conflicts."""
    plan = build_plan(repo)
    open_actionable = list(plan.now) + [item.note for item in plan.blocked]
    ready = tuple(sorted(plan.now, key=_due_key))
    scheduled = tuple(sorted((note for note in open_actionable if note.due), key=_due_key))
    return Timeline(
        ready=ready,
        waiting=plan.blocked,  # already in dependency order, each with its blockers
        scheduled=scheduled,
        conflicts=_timeline_conflicts(plan),
    )


def _timeline_conflicts(plan: Plan) -> tuple[str, ...]:
    """Infeasibilities the user must resolve: due-before-prerequisite, and dependency cycles."""
    out: list[str] = []
    for nid, prereqs in plan.deps.items():
        note = plan.by_id.get(nid)
        if note is None or not note.due:
            continue
        for prereq_id in prereqs:
            prereq = plan.by_id.get(prereq_id)
            if prereq is not None and prereq.due and note.due < prereq.due:
                out.append(
                    f"{note.title} (due {note.due}) is due before its prerequisite "
                    f"{prereq.title} (due {prereq.due})"
                )
    if plan.cycle:
        out.append("dependency cycle: " + ", ".join(note.title for note in plan.cycle))
    return tuple(out)


def render_timeline(timeline: Timeline) -> str:
    lines = [
        "# Timeline",
        "",
        f"> {_TIMELINE_MARKER} — projected from dependencies + due dates. Edit the notes, not this file.",
        "",
        "## Ready now",
        "",
    ]
    if timeline.ready:
        lines += [f"- [ ] {note.title}{_due_suffix(note)}" for note in timeline.ready]
    else:
        lines.append("_Nothing is ready — everything is blocked or done._")
    lines += ["", "## Waiting", ""]
    if timeline.waiting:
        for item in timeline.waiting:
            blockers = ", ".join(blocker.title for blocker in item.blocked_by)
            lines.append(f"- {item.note.title}{_due_suffix(item.note)} — waiting on: {blockers}")
    else:
        lines.append("_Nothing is waiting._")
    if timeline.scheduled:
        lines += ["", "## Scheduled by date", ""]
        lines += [f"- {note.due}: {note.title}" for note in timeline.scheduled]
    if timeline.conflicts:
        lines += ["", "## ⚠ Conflicts", ""]
        lines += [f"- {conflict}" for conflict in timeline.conflicts]
    return "\n".join(lines) + "\n"


def _due_suffix(note: Note) -> str:
    return f"  (due: {note.due})" if note.due else ""


def write_timeline(repo: NoteRepository, path: Path) -> Path:
    path.write_text(render_timeline(build_timeline(repo)), encoding="utf-8")
    return path


def _actionable(note: Note, status: NoteStatus) -> bool:
    # `status` is the derived current status (ADR-0008), not necessarily the note's creation status.
    # NEEDS_REVIEW is excluded: a note flagged by an unresolved contradiction (US-10) must be
    # resolved in the "Needs review" section first, not presented as immediately actionable.
    return note.type is NoteType.TASK and status not in {
        NoteStatus.DONE,
        NoteStatus.SUPERSEDED,
        NoteStatus.NEEDS_REVIEW,
    }


def _dependencies(repo: NoteRepository, notes: dict[str, Note]) -> dict[str, set[str]]:
    deps: dict[str, set[str]] = {nid: set() for nid in notes}
    for edge in repo.edges():
        if edge.source_id not in notes or edge.target_id not in notes:
            continue
        if edge.kind is EdgeKind.DEPENDS_ON:
            deps[edge.source_id].add(edge.target_id)
        elif edge.kind is EdgeKind.WAITING_ON:
            # waiting_on is a (soft, external) prerequisite for scheduling: the source can't proceed
            # until the target is done — same effect on the DAG as depends_on (ADR-0007/PR-G).
            deps[edge.source_id].add(edge.target_id)
        elif edge.kind is EdgeKind.BLOCKS:
            deps[edge.target_id].add(
                edge.source_id
            )  # source blocks target ⇒ target depends on source
        elif edge.kind is EdgeKind.NEXT:
            # `next` is explicit sequencing: source THEN target ⇒ target depends on source (do the
            # source first). Same DAG effect as `blocks`, but a softer "recommended order" intent.
            deps[edge.target_id].add(edge.source_id)
    return deps


def _toposort(notes: dict[str, Note], deps: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    indegree = {nid: len(deps[nid]) for nid in notes}
    dependents: dict[str, list[str]] = {nid: [] for nid in notes}
    for nid in notes:
        for prereq in deps[nid]:
            dependents[prereq].append(nid)

    # Min-heap keyed on note id: pops the smallest ready id at each step (same deterministic order
    # as the previous sort-and-pop-front), but in O((V+E) log V) instead of re-sorting the frontier
    # on every pop (the old O(V^2 log V) that grew with the whole vault on each re-projection).
    ready = [nid for nid in notes if indegree[nid] == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        current = heapq.heappop(ready)
        order.append(current)
        for dependent in dependents[current]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, dependent)

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
        box = "[x] " if plan.status_by_id[nid] is NoteStatus.DONE else "[ ] "
    else:
        box = ""
    out = [f"{indent}- {box}{note.title} _({note.type.value}/{note.horizon.value})_"]
    for child in plan.child_ids.get(nid, ()):
        out += _render_tree(plan, child, depth + 1)
    return out
