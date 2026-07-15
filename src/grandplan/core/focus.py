"""Focus views — what to actually do next, projected from the dependency DAG (SPEC-ACT §A1).

`core/schedule` already answers the three questions that matter once a vault is full: what's the
bottleneck (`critical_path`), what can run concurrently (`parallel_batches`), and how far along is
each goal (`roll_up_progress`). Nothing put those answers on the **chat** surface, so asking "what's
the hardest thing?" there retrieved six semantically-similar notes and guessed. This module closes
that, in two shapes:

- `render_focus` — the deterministic `/focus` view. Pure projection, **no model call**: the priority
  view has to stay correct and available when Ollama is down or unpulled (SPEC-ACT §3).
- `plan_context_block` — a bounded block for the chat prompt, so a *natural-language* priority
  question is grounded in the real graph rather than in whatever matched the question's wording.

Both are pure functions of a `Plan`. Every list is capped and **every truncation is announced**: the
context window is finite, and a silently-truncated list reads to a model as a complete one.
"""

from __future__ import annotations

from collections.abc import Sequence

from grandplan.core.models import Note
from grandplan.core.planner import Plan
from grandplan.core.schedule import critical_path, parallel_batches, roll_up_progress

# Caps (SPEC-ACT §4.2). Retrieval already spends ~4.2 KB of the 8192-token default context (6 notes
# × 700 chars) before history; these keep the plan block from crowding out the notes it sits beside.
_PATH_CAP = 8
_NOW_CAP = 8
_BATCH_CAP = 3  # batches shown
_BATCH_ITEMS = 5  # notes shown per batch
_PROGRESS_CAP = 5

_CONTEXT_HEADER = (
    "PLAN CONTEXT — authoritative for priority, sequence, and progress questions; the NOTES above "
    "are authoritative for content. Derived from the dependency graph, not from similarity."
)


def _label(note: Note) -> str:
    """A note as `Title [id]` — never its body (that is what the retrieval section is for)."""
    return f"{note.title} [{note.id}]"


def _inline(notes: Sequence[Note], cap: int) -> str:
    """`A [a]; B [b]; … +N more` — one line, capped, truncation stated."""
    shown = "; ".join(_label(note) for note in notes[:cap])
    extra = len(notes) - cap
    return f"{shown}; … +{extra} more" if extra > 0 else shown


def _more(total: int, cap: int) -> str:
    return f"\n  … +{total - cap} more" if total > cap else ""


def plan_context_block(plan: Plan) -> str:
    """A bounded `PLAN CONTEXT` block for the chat prompt; `""` when nothing is open.

    Empty is deliberate: a block with no content invites the model to fill the silence, so an empty
    plan is better expressed by the block's absence than by an empty heading.
    """
    path = critical_path(plan)
    progress = roll_up_progress(plan)
    if not (path or plan.now or progress):
        return ""
    lines = [_CONTEXT_HEADER]
    if path:
        lines.append(
            f"critical path (longest chain of open work, in order): {_inline(path, _PATH_CAP)}"
        )
    if plan.now:
        lines.append(f"actionable now (nothing blocking these): {_inline(plan.now, _NOW_CAP)}")
    if progress:
        shown = "; ".join(
            f"{p.note.title} [{p.note.id}] {p.percent}% ({p.done}/{p.total})"
            for p in progress[:_PROGRESS_CAP]
        )
        extra = len(progress) - _PROGRESS_CAP
        lines.append(f"progress: {shown}" + (f"; … +{extra} more" if extra > 0 else ""))
    return "\n".join(lines)


def render_focus(plan: Plan) -> str:
    """The `/focus` view: bottleneck → now → parallelizable → progress. No model involved."""
    path = critical_path(plan)
    batches = parallel_batches(plan)
    progress = roll_up_progress(plan)
    parts = ["FOCUS — what to do next"]

    if plan.cycle:
        # Cycle notes never resolve a dependency depth, so they are absent from the bottleneck and
        # the batches below. Rendering that silently would read as "no work left" — the opposite of
        # the truth — so name them as infeasible-until-broken instead.
        listed = "; ".join(_label(note) for note in plan.cycle[:_PATH_CAP])
        parts.append(
            "⚠ dependency cycle — these notes depend on each other, so they can never be sequenced "
            f"and are excluded from everything below. Break one link to unblock them:\n  {listed}"
            + _more(len(plan.cycle), _PATH_CAP)
        )

    if path:
        listed = "\n".join(
            f"  {i}. {_label(note)}" for i, note in enumerate(path[:_PATH_CAP], start=1)
        )
        parts.append(
            f"Bottleneck — the longest chain of open work ({len(path)} steps). Its length is the "
            f"minimum number of sequential steps left, so this is what to protect:\n{listed}"
            + _more(len(path), _PATH_CAP)
        )

    if plan.now:
        listed = "\n".join(f"  - {_label(note)}" for note in plan.now[:_NOW_CAP])
        parts.append(
            f"Actionable now — nothing is blocking these:\n{listed}"
            + _more(len(plan.now), _NOW_CAP)
        )

    if len(batches) > 1:  # a single batch is just `now` again — no parallelism to report
        listed = "\n".join(
            f"  batch {i}: {_inline(batch, _BATCH_ITEMS)}"
            for i, batch in enumerate(batches[:_BATCH_CAP], start=1)
        )
        parts.append(
            f"Can run in parallel — everything in a batch is independent; batch k unlocks once "
            f"batch k−1 is done:\n{listed}" + _more(len(batches), _BATCH_CAP)
        )

    if progress:
        listed = "\n".join(
            f"  {p.note.title}  [{p.note.id}]  {p.percent}% ({p.done}/{p.total} tasks done)"
            for p in progress[:_PROGRESS_CAP]
        )
        parts.append(f"Progress:\n{listed}" + _more(len(progress), _PROGRESS_CAP))

    if len(parts) == 1:  # header only — nothing to report at all
        parts.append("nothing open — no actionable tasks in this vault.")
    return "\n\n".join(parts)
