"""Renderers — project the knowledge graph into stand-alone deliverables (ROADMAP theme E).

The vault's `.md`/`Plan.md`/`Masterplan.md`/`Timeline.md` are *live projections* meant to be browsed
in Obsidian. A **deliverable** is different: one self-contained document you hand to someone — an
executive summary of where everything stands. This is the second renderer (after the Markdown vault),
proving "knowledge → deliverable" and giving agents something concrete to *generate*.

`Renderer` is a Strategy port (ADR-0003): `render(repo, originals) -> str` returns a finished
document. `MarkdownReportRenderer` composes the existing projections (plan, masterplan, timeline,
health report) into one offline, deterministic Markdown report — pure, so it is fully gated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from grandplan.core.planner import (
    Plan,
    Timeline,
    build_plan,
    build_timeline,
)
from grandplan.core.ports import NoteRepository
from grandplan.core.report import build_run_report
from grandplan.core.schedule import critical_path, parallel_batches, roll_up_progress
from grandplan.core.store import OriginalStore

_HORIZON_LABELS: tuple[tuple[str, str], ...] = (
    ("goal", "Goals"),
    ("project", "Projects"),
    ("action", "Actions & ideas"),
)


class Renderer(Protocol):
    """Render the knowledge graph into a stand-alone document (Strategy)."""

    def render(self, repo: NoteRepository, originals: OriginalStore) -> str: ...


@dataclass(frozen=True)
class MarkdownReportRenderer:
    """Compose plan + masterplan + timeline + health into one self-contained Markdown report.

    `title` heads the document; `created` (caller-supplied, no hidden clock) dates it. Deterministic
    and offline: the same graph + inputs always render byte-identical output.
    """

    title: str = "grandplan report"
    created: str = ""

    def render(self, repo: NoteRepository, originals: OriginalStore) -> str:
        plan = build_plan(repo)
        timeline = build_timeline(repo)
        report = build_run_report(repo, originals)
        lines: list[str] = [f"# {self.title}", ""]
        if self.created:
            lines += [
                f"> Generated {self.created} — a snapshot projection of the knowledge graph.",
                "",
            ]
        else:
            lines += ["> A snapshot projection of the knowledge graph.", ""]
        lines += self._summary(plan, report.note_count)
        lines += self._progress(plan)
        lines += self._priorities(plan)
        lines += self._critical_path(plan)
        lines += self._parallel_batches(plan)
        lines += self._blocked(plan)
        lines += self._schedule(timeline)
        lines += self._by_horizon(plan)
        lines += self._open_questions(plan)
        lines += self._health(report.structural_edges, report.semantic_edges, report.isolated)
        return "\n".join(lines).rstrip() + "\n"

    def _summary(self, plan: Plan, note_count: int) -> list[str]:
        blocked = len(plan.blocked)
        return [
            "## Summary",
            "",
            f"- **{note_count}** notes tracked.",
            f"- **{len(plan.now)}** ready to act on now; **{blocked}** blocked; "
            f"**{len(plan.needs_review)}** need review.",
            f"- **{len(plan.root_ids)}** top-level goals/projects.",
            "",
        ]

    def _progress(self, plan: Plan) -> list[str]:
        rolled = roll_up_progress(plan)
        if not rolled:
            return []
        lines = ["## Progress (goals & projects)", ""]
        for item in rolled:
            lines.append(
                f"- {item.note.title} — **{item.percent}%** ({item.done}/{item.total} tasks done)"
            )
        return [*lines, ""]

    def _priorities(self, plan: Plan) -> list[str]:
        lines = ["## Top priorities (do now)", ""]
        if plan.now:
            lines += [f"- [ ] {note.title}" for note in plan.now]
        else:
            lines.append("_Nothing actionable and unblocked._")
        return [*lines, ""]

    def _critical_path(self, plan: Plan) -> list[str]:
        path = critical_path(plan)
        if len(path) < 2:  # a 0/1-step "chain" isn't a meaningful bottleneck
            return []
        lines = ["## Critical path (the bottleneck)", ""]
        lines.append(" → ".join(note.title for note in path))
        lines += [
            "",
            f"_{len(path)} sequential steps — the minimum left if nothing is parallelized._",
        ]
        return [*lines, ""]

    def _parallel_batches(self, plan: Plan) -> list[str]:
        batches = parallel_batches(plan)
        # Only worth showing when at least one batch has >1 task (i.e. something can be parallelized).
        if not any(len(batch) > 1 for batch in batches):
            return []
        lines = ["## Parallel batches (do each batch concurrently)", ""]
        for i, batch in enumerate(batches, 1):
            titles = ", ".join(note.title for note in batch)
            lines.append(f"{i}. {titles}")
        return [*lines, ""]

    def _blocked(self, plan: Plan) -> list[str]:
        if not plan.blocked:
            return []
        lines = ["## Blocked", ""]
        for item in plan.blocked:
            blockers = ", ".join(b.title for b in item.blocked_by)
            lines.append(f"- {item.note.title} — waiting on: {blockers}")
        return [*lines, ""]

    def _schedule(self, timeline: Timeline) -> list[str]:
        if not timeline.scheduled:
            return []
        lines = ["## Scheduled (by date)", ""]
        lines += [f"- {note.due} — {note.title}" for note in timeline.scheduled]
        return [*lines, ""]

    def _by_horizon(self, plan: Plan) -> list[str]:
        lines = ["## By horizon", ""]
        roots_by_horizon: dict[str, list[str]] = {}
        for root_id in plan.root_ids:
            horizon = plan.by_id[root_id].horizon.value
            roots_by_horizon.setdefault(horizon, []).append(root_id)
        any_rendered = False
        for horizon, label in _HORIZON_LABELS:
            ids = roots_by_horizon.get(horizon, [])
            if not ids:
                continue
            any_rendered = True
            lines += [f"### {label}", ""]
            for root_id in ids:
                lines += self._tree(plan, root_id, 0)
            lines.append("")
        if not any_rendered:
            lines += ["_No structured hierarchy yet._", ""]
        return lines

    def _tree(self, plan: Plan, note_id: str, depth: int) -> list[str]:
        note = plan.by_id[note_id]
        status = plan.status_by_id.get(note_id)
        mark = " ✓" if status is not None and status.value == "done" else ""
        out = [f"{'  ' * depth}- {note.title}{mark}"]
        for child in plan.child_ids.get(note_id, ()):
            out += self._tree(plan, child, depth + 1)
        return out

    def _open_questions(self, plan: Plan) -> list[str]:
        if not plan.needs_review:
            return []
        lines = ["## Open questions / needs review", ""]
        lines += [f"- {note.title}" for note in plan.needs_review]
        for src, tgt in plan.contradictions:
            a, b = plan.by_id.get(src), plan.by_id.get(tgt)
            if a is not None and b is not None:
                lines.append(f"  - contradiction: {a.title} ⟷ {b.title}")
        return [*lines, ""]

    def _health(self, structural: int, semantic: int, isolated: tuple[str, ...]) -> list[str]:
        return [
            "## Graph health",
            "",
            f"- {structural} structural edges, {semantic} semantic edges.",
            f"- {len(isolated)} isolated notes (no connections).",
            "",
        ]
