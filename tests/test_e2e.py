"""End-to-end offline test of the whole capture pipeline (everything but the Qt shell).

Drives the same view-model + adapters the GUI wires together — persistent stores, the offline
organizer/embedder, reconciliation, vault writing, and projections — to prove the full
experience works together and stays connected across a restart. Fully deterministic and offline.
"""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.app.review import StatusUpdateResult, approve, start_review
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import NoteStatus, Source
from grandplan.core.note_store import JsonlNoteRepository
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.project import write_projections
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.store import JsonlOriginalStore
from grandplan.core.update_detect import HeuristicUpdateDetector
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


def _index(vault: Path) -> Path:
    return vault / ".grandplan" / "index.jsonl"


def _inbox(vault: Path) -> Path:
    return vault / ".grandplan" / "inbox.jsonl"


def _start(text: str, repo: JsonlNoteRepository, originals: JsonlOriginalStore, *, detector=None):  # type: ignore[no-untyped-def]
    return start_review(
        text,
        created=_CREATED,
        source=_SOURCE,
        organizer=HeuristicOrganizer(),
        embedder=HashingEmbedder(),
        reconciler=SimilarityReconciler(),
        repo=repo,
        originals=originals,
        detector=detector,
    )


def test_capture_driven_status_update_survives_reopen_and_reprojects(tmp_path: Path) -> None:
    """PR-B end-to-end: a later 'done ...' capture matches a seeded task and (on approve) flips its
    derived status to DONE — event-sourced (no second note), persisted across a reopen, removing the
    task from Plan.md's "Now"."""
    vault = tmp_path / "vault"
    writer = MarkdownVaultWriter(vault)

    # Session 1: seed an actionable task and project it — it shows up under "Now".
    repo1 = JsonlNoteRepository(_index(vault))
    originals1 = JsonlOriginalStore(_inbox(vault))
    first = approve(
        _start("finish the bug bounty finder tool", repo1, originals1),
        repo=repo1,
        vault=writer,
        link_related=True,
    )
    assert not isinstance(first, StatusUpdateResult)  # a real new note
    write_projections(repo1, vault)
    now_before = (
        (vault / "Plan.md")
        .read_text(encoding="utf-8")
        .split("## Now", 1)[1]
        .split("## Blocked", 1)[0]
    )
    assert first.note.title in now_before

    # Session 2 (fresh repo rehydrated from disk): a "done" capture matches the task → status update.
    repo2 = JsonlNoteRepository(_index(vault))
    originals2 = JsonlOriginalStore(_inbox(vault))
    pending = _start(
        "done with the bug bounty finder tool",
        repo2,
        originals2,
        detector=HeuristicUpdateDetector(),
    )
    assert pending.update is not None and pending.update.status is NoteStatus.DONE
    result = approve(pending, repo=repo2, vault=writer)
    assert isinstance(result, StatusUpdateResult)
    write_projections(repo2, vault)

    # Session 3 (reopen): the status event persisted; derived status is DONE; still ONE note.
    repo3 = JsonlNoteRepository(_index(vault))
    assert len(repo3.notes()) == 1  # the update created no second note (lossless/event-sourced)
    assert repo3.status_of(first.note.id) is NoteStatus.DONE
    now_after = (
        (vault / "Plan.md")
        .read_text(encoding="utf-8")
        .split("## Now", 1)[1]
        .split("## Blocked", 1)[0]
    )
    assert first.note.title not in now_after  # the completed task left "Now"
