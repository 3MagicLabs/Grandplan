"""End-to-end offline test of the whole capture pipeline (everything but the Qt shell).

Drives the same view-model + adapters the GUI wires together — persistent stores, the offline
organizer/embedder, reconciliation, vault writing, and projections — to prove the full
experience works together and stays connected across a restart. Fully deterministic and offline.
"""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.app.review import approve, start_review
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Source
from grandplan.core.note_store import JsonlNoteRepository
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.project import write_projections
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.store import JsonlOriginalStore
from grandplan.core.vault import MarkdownVaultWriter

_SOURCE = Source(app="grandplan", title="capture")
_CREATED = "2026-06-15T00:00:00Z"


def _capture(text: str, vault_dir: Path) -> None:
    """One full capture+approve, wiring the persistent stores exactly like the GUI does."""
    repo = JsonlNoteRepository(vault_dir / ".grandplan" / "index.jsonl")
    originals = JsonlOriginalStore(vault_dir / ".grandplan" / "inbox.jsonl")
    pending = start_review(
        text,
        created=_CREATED,
        source=_SOURCE,
        organizer=HeuristicOrganizer(),
        embedder=HashingEmbedder(),
        reconciler=SimilarityReconciler(),
        repo=repo,
        originals=originals,
    )
    approve(pending, repo=repo, vault=MarkdownVaultWriter(vault_dir), link_related=True)
    write_projections(repo, vault_dir)


def test_full_pipeline_connects_persists_and_plans(tmp_path: Path) -> None:
    vault = tmp_path / "vault"

    # Two related captures, each in its own session (fresh stores) — the index must rehydrate
    # from disk so the second links to the first (the cross-session linking fix).
    _capture("machine learning notes about neural networks", vault)
    _capture("neural networks and deep learning study", vault)

    notes = sorted(p for p in vault.glob("*.md") if p.name != "Plan.md")
    assert len(notes) == 2

    # Connection: at least one note carries a RESOLVABLE wikilink (filename stem + title), and
    # no dangling bare-id link of the phantom-node form.
    bodies = [p.read_text(encoding="utf-8") for p in notes]
    assert any(
        "|" in line
        for body in bodies
        for line in body.splitlines()
        if line.startswith("- relates [[")
    )

    # Clean Obsidian frontmatter: flattened source, alias for id resolution, no JSON-object blob.
    front = bodies[0].split("\n---", 1)[0]
    assert "source_app:" in front
    assert "aliases:" in front
    assert "source: {" not in front

    # Rehydration: a brand-new repository instance reads both notes + the edge back from disk.
    reopened = JsonlNoteRepository(vault / ".grandplan" / "index.jsonl")
    assert len(reopened.notes()) == 2
    assert len(reopened.edges()) >= 1

    # Projections: actionable plan with a Mermaid map, and a JSON graph matching the notes.
    plan = (vault / "Plan.md").read_text(encoding="utf-8")
    assert "# Plan" in plan
    assert "```mermaid" in plan
    assert "-.->|related|" in plan  # the semantic connection shows in the diagram
    graph = json.loads((vault / "graph.json").read_text(encoding="utf-8"))
    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) >= 1
