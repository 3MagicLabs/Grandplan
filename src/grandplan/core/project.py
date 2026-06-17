"""Vault projections — regenerate the derived views (graph.json + Plan.md) from the graph.

A note's truth lives in the graph (notes + typed edges); the JSON graph and the actionable
`Plan.md` (with its Mermaid diagram) are pure projections of it (SPEC §11 "one source, three
views"). Both the CLI and the GUI call this after a write so the plan stays current — the
"grand plan" materializes as notes are captured.
"""

from __future__ import annotations

from pathlib import Path

from grandplan.core.graph import export_graph
from grandplan.core.planner import write_plan
from grandplan.core.ports import NoteRepository


def write_projections(repo: NoteRepository, vault_dir: Path) -> tuple[Path, Path]:
    """Write `graph.json` + `Plan.md` into `vault_dir`; return their paths. Idempotent."""
    vault_dir.mkdir(parents=True, exist_ok=True)
    graph_path = export_graph(repo, vault_dir / "graph.json")
    plan_path = write_plan(repo, vault_dir / "Plan.md")
    return graph_path, plan_path
