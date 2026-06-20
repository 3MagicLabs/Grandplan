"""Scheduling analytics over the dependency DAG — critical path + parallel batches (ROADMAP theme C).

The planner already splits notes into now/blocked and a feasible timeline. This adds two derived
*scheduling* views over the same `depends_on`/`blocks`/`waiting_on` DAG, both pure functions of a
`Plan`:

- **critical path** — the longest chain of still-open, actionable, dependency-linked tasks. This is
  the bottleneck: its length is the minimum number of sequential steps left, so it's what to protect.
- **parallel batches** — open actionable tasks grouped by dependency depth. Everything in batch *k*
  can be worked **concurrently** once batch *k−1* is done, so it answers "what can we parallelize?".

Both consider only *open* tasks (a DONE prerequisite is already satisfied, so it no longer sequences
work) and skip notes in a dependency cycle (the planner reports those separately as infeasible).
"""

from __future__ import annotations

from collections.abc import Iterable

from dataclasses import dataclass

from grandplan.core.models import Note, NoteStatus, NoteType
from grandplan.core.planner import Plan

_DONE = {NoteStatus.DONE, NoteStatus.SUPERSEDED}
_GOAL_LIKE = {NoteType.GOAL, NoteType.PROJECT}


def _open_actionable_ids(plan: Plan) -> set[str]:
    """Ids of tasks that still need doing: in `now` or `blocked` (already actionable + not done)."""
    ids = {note.id for note in plan.now}
    ids |= {item.note.id for item in plan.blocked}
    return ids


def _open_prereqs(plan: Plan, open_ids: set[str]) -> dict[str, tuple[str, ...]]:
    """Each open task's prerequisites that are themselves still open (done prereqs drop out)."""
    return {
        nid: tuple(p for p in plan.deps.get(nid, ()) if p in open_ids and not _is_done(plan, p))
        for nid in open_ids
    }


def _is_done(plan: Plan, nid: str) -> bool:
    return plan.status_by_id.get(nid) in _DONE


def _depths(plan: Plan, open_ids: set[str]) -> dict[str, int]:
    """Dependency depth of each open task (0 = no open prereqs), computed in topological order.

    Notes in a dependency cycle never reach depth (their prereqs aren't all resolved), so they're
    naturally excluded — matching the planner, which surfaces cycles as conflicts instead.
    """
    prereqs = _open_prereqs(plan, open_ids)
    depth: dict[str, int] = {}
    for note in plan.ordered:  # topological order: every prerequisite is seen before its dependent
        nid = note.id
        if nid not in open_ids:
            continue
        parents = [p for p in prereqs[nid] if p in depth]
        if len(parents) != len(prereqs[nid]):  # pragma: no cover - defensive
            # Unreachable for a valid topological `ordered`: every open prerequisite precedes its
            # dependent and so already has a depth. Kept as a guard against a malformed order.
            continue
        depth[nid] = 1 + max((depth[p] for p in parents), default=-1)
    return depth


def critical_path(plan: Plan) -> tuple[Note, ...]:
    """The longest chain of open, dependency-linked tasks (prerequisite → … → dependent).

    Returns the chain in execution order (do the first one first). Empty when nothing is open. Ties
    break deterministically by note id, so the path is stable across re-projections.
    """
    open_ids = _open_actionable_ids(plan)
    depth = _depths(plan, open_ids)
    if not depth:
        return ()
    prereqs = _open_prereqs(plan, open_ids)
    chain: list[str] = [_deepest(depth, depth.keys())]
    while prereqs[chain[-1]]:
        resolved = [p for p in prereqs[chain[-1]] if p in depth]
        if not resolved:  # pragma: no cover - defensive
            # Unreachable: a note only has a depth once all its open prereqs do, so a node on the
            # path with prerequisites always has at least one resolved prerequisite to follow.
            break
        chain.append(_deepest(depth, resolved))
    chain.reverse()  # prerequisite-first (execution order)
    return tuple(plan.by_id[nid] for nid in chain)


def _deepest(depth: dict[str, int], ids: Iterable[str]) -> str:
    """The id with the greatest depth; ties broken by the smallest id (deterministic)."""
    candidates = list(ids)
    top = max(depth[nid] for nid in candidates)
    return min(nid for nid in candidates if depth[nid] == top)


def parallel_batches(plan: Plan) -> tuple[tuple[Note, ...], ...]:
    """Open tasks grouped by dependency depth: batch *k* can run once batch *k−1* is done.

    Each batch's notes are independent of one another, so they can be worked concurrently. Batches
    are ordered earliest-first; within a batch, notes are sorted by title then id (stable).
    """
    open_ids = _open_actionable_ids(plan)
    depth = _depths(plan, open_ids)
    if not depth:
        return ()
    by_depth: dict[int, list[str]] = {}
    for nid, level in depth.items():
        by_depth.setdefault(level, []).append(nid)
    return tuple(
        tuple(
            plan.by_id[nid]
            for nid in sorted(by_depth[level], key=lambda i: (plan.by_id[i].title, i))
        )
        for level in sorted(by_depth)
    )


@dataclass(frozen=True)
class Progress:
    """How far along a goal/project is, rolled up from its descendant tasks (OKR-style)."""

    note: Note
    done: int
    total: int

    @property
    def percent(self) -> int:
        """Completion as a 0–100 integer (0 when there are no tasks under it)."""
        return round(100 * self.done / self.total) if self.total else 0


def roll_up_progress(plan: Plan) -> tuple[Progress, ...]:
    """Progress for each goal/project, from the share of its descendant tasks that are done.

    Walks the `part_of` hierarchy; a node's denominator is every `task` under it (at any depth), the
    numerator those that are done/superseded. Goals/projects with no task descendants are omitted (no
    meaningful percentage). Ordered by horizon (goals before projects), then title — stable.
    """

    def _tally(note_id: str) -> tuple[int, int]:
        done = total = 0
        for child_id in plan.child_ids.get(note_id, ()):
            child = plan.by_id.get(child_id)
            if child is None:  # pragma: no cover - defensive; child_ids only holds known note ids
                continue
            if child.type is NoteType.TASK:
                total += 1
                if plan.status_by_id.get(child_id) in _DONE:
                    done += 1
            child_done, child_total = _tally(child_id)
            done += child_done
            total += child_total
        return done, total

    out: list[Progress] = []
    for note in plan.by_id.values():
        if note.type not in _GOAL_LIKE:
            continue
        done, total = _tally(note.id)
        if total:
            out.append(Progress(note=note, done=done, total=total))
    return tuple(sorted(out, key=lambda p: (p.note.horizon.value, p.note.title, p.note.id)))
