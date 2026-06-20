"""Vault health/run report — a comprehensive "what happened / what went wrong" summary.

Powers both the `organize`/`regenerate` command output and the `doctor` command. From the derived
graph (notes + typed edges) + the stored originals it computes: note/type/horizon counts, the edge
breakdown split into **structural** (part_of/depends_on/blocks/next — the planning skeleton) vs
**semantic** (relates/builds_on/… — similarity links), isolated notes (no edges), and low-quality
notes (QAS-8). A run with zero structural edges and all-low-quality notes is the exact fingerprint
of "the LLM never ran and nothing was placed into the graph" — surfaced plainly, not buried.
Pure, offline, deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from grandplan.core.densify import suggest_mention_links
from grandplan.core.models import EdgeKind
from grandplan.core.ports import NoteRepository
from grandplan.core.quality import note_quality_issues
from grandplan.core.store import OriginalStore

# Edges that form the planning skeleton (hierarchy + dependency DAG) vs. mere similarity links.
_STRUCTURAL: frozenset[EdgeKind] = frozenset(
    {EdgeKind.PART_OF, EdgeKind.DEPENDS_ON, EdgeKind.BLOCKS, EdgeKind.NEXT}
)


@dataclass(frozen=True)
class RunReport:
    """A snapshot of a vault's graph quality (drives both the run summary and `doctor`)."""

    note_count: int
    type_counts: Mapping[str, int]
    horizon_counts: Mapping[str, int]
    edge_counts: Mapping[str, int]
    structural_edges: int
    semantic_edges: int
    isolated: tuple[str, ...]  # titles of notes with no edge at all
    low_quality: tuple[tuple[str, tuple[str, ...]], ...]  # (title, issues) for each flagged note
    missing_links: tuple[
        tuple[str, str], ...
    ]  # (source, target) titles: body names target, no edge yet


def build_run_report(repo: NoteRepository, originals: OriginalStore) -> RunReport:
    notes = repo.current_notes()
    edges = repo.edges()

    type_counts: dict[str, int] = {}
    horizon_counts: dict[str, int] = {}
    for note in notes:
        type_counts[note.type.value] = type_counts.get(note.type.value, 0) + 1
        horizon_counts[note.horizon.value] = horizon_counts.get(note.horizon.value, 0) + 1

    edge_counts: dict[str, int] = {}
    structural = semantic = 0
    connected: set[str] = set()
    for edge in edges:
        edge_counts[edge.kind.value] = edge_counts.get(edge.kind.value, 0) + 1
        if edge.kind in _STRUCTURAL:
            structural += 1
        else:
            semantic += 1
        connected.add(edge.source_id)
        connected.add(edge.target_id)

    isolated = tuple(note.title for note in notes if note.id not in connected)

    # Possible missing links: a note's body literally names another note's title, yet no edge connects
    # them (in either direction). Offline title-mention detection (densify) — a read-only suggestion.
    linked_pairs = {frozenset((e.source_id, e.target_id)) for e in edges}
    missing_links = tuple(
        (note.title, target.title)
        for note in notes
        for target in suggest_mention_links(note, notes)
        if frozenset((note.id, target.id)) not in linked_pairs
    )

    low_quality: list[tuple[str, tuple[str, ...]]] = []
    for note in notes:
        original = originals.get(note.original_id)
        if original is None:
            continue
        issues = note_quality_issues(note, original)
        if issues:
            low_quality.append((note.title, issues))

    return RunReport(
        note_count=len(notes),
        type_counts=type_counts,
        horizon_counts=horizon_counts,
        edge_counts=edge_counts,
        structural_edges=structural,
        semantic_edges=semantic,
        isolated=isolated,
        low_quality=tuple(low_quality),
        missing_links=missing_links,
    )


def _counts_line(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{key}: {value}" for key, value in sorted(counts.items())) or "none"


def render_report(report: RunReport, *, organizer_label: str) -> str:
    """A compact, human-readable diagnostic block for the terminal."""
    lines = [
        "── grandplan report ─────────────────────────────",
        f"organizer:  {organizer_label}",
        f"notes:      {report.note_count}  ({_counts_line(report.type_counts)})",
        f"horizons:   {_counts_line(report.horizon_counts)}",
        f"edges:      {report.structural_edges} structural + {report.semantic_edges} semantic"
        f"  ({_counts_line(report.edge_counts)})",
    ]
    # The two headline failure modes, called out explicitly so a test run is self-diagnosing.
    if report.note_count and report.structural_edges == 0:
        lines.append(
            "  ⚠ no structural edges (part_of/depends_on) — the plan has no hierarchy or sequence"
        )
    if report.low_quality:
        share = f"{len(report.low_quality)}/{report.note_count}"
        lines.append(f"  ⚠ {share} notes look un-organized (QAS-8):")
        for title, issues in report.low_quality[:10]:
            lines.append(f"      • {title[:48]!r}: {'; '.join(issues)}")
        if len(report.low_quality) > 10:
            lines.append(f"      … and {len(report.low_quality) - 10} more")
        if len(report.low_quality) == report.note_count:
            lines.append("      → every note is low-quality: the local model likely never ran")
    if report.isolated:
        lines.append(f"  ⚠ {len(report.isolated)} isolated note(s) with no connections")
    if report.missing_links:
        lines.append(
            f"  → {len(report.missing_links)} possible missing link(s) (a note names another):"
        )
        for source, target in report.missing_links[:10]:
            lines.append(f"      • {source[:32]!r} → {target[:32]!r}")
        if len(report.missing_links) > 10:
            lines.append(f"      … and {len(report.missing_links) - 10} more")
    lines.append("─────────────────────────────────────────────────")
    return "\n".join(lines)
