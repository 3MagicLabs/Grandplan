"""End-to-end offline test of the whole capture pipeline (everything but the Qt shell).

Drives the same view-model + adapters the GUI wires together — persistent stores, the offline
organizer/embedder, reconciliation, vault writing, and projections — to prove the full
experience works together and stays connected across a restart. Fully deterministic and offline.
"""

from __future__ import annotations

import json
from pathlib import Path

from grandplan.app.review import EditResult, StatusUpdateResult, approve, start_review
from grandplan.core.edit_detect import HeuristicEditDetector
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

    notes = sorted(
        p
        for p in vault.glob("*.md")
        if p.name not in ("Plan.md", "Masterplan.md", "Timeline.md", "_grandplan-guide.md")
    )
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


def _start(  # type: ignore[no-untyped-def]
    text: str,
    repo: JsonlNoteRepository,
    originals: JsonlOriginalStore,
    *,
    detector=None,
    edit_detector=None,
):
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
        edit_detector=edit_detector,
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


def test_capture_driven_edit_re_renders_note_and_survives_reopen(tmp_path: Path) -> None:
    """PR-C end-to-end: a later 'rename … to …' capture edits a seeded note's title (an event, no
    new note); the re-rendered .md shows the new title + a History section, it survives a reopen, and
    Plan.md's 'What moved' digest records it."""
    vault = tmp_path / "vault"
    writer = MarkdownVaultWriter(vault)

    # Session 1: seed a note and project (re-rendering its .md from derived state).
    repo1 = JsonlNoteRepository(_index(vault))
    originals1 = JsonlOriginalStore(_inbox(vault))
    first = approve(
        _start("draft the bug bounty finder tool", repo1, originals1), repo=repo1, vault=writer
    )
    assert isinstance(first, EditResult) is False  # a real new note
    write_projections(repo1, vault, originals=originals1)

    # Session 2 (fresh repo from disk): a "rename" capture edits the note's title.
    repo2 = JsonlNoteRepository(_index(vault))
    originals2 = JsonlOriginalStore(_inbox(vault))
    pending = _start(
        "rename the bug bounty finder tool to bounty hunter",
        repo2,
        originals2,
        edit_detector=HeuristicEditDetector(),
    )
    assert pending.edit is not None and pending.edit.edit.title == "bounty hunter"
    result = approve(pending, repo=repo2, vault=writer)
    assert isinstance(result, EditResult)
    write_projections(repo2, vault, originals=originals2)

    # Session 3 (reopen): the edit persisted; derived title changed; still ONE note; no orphan file.
    repo3 = JsonlNoteRepository(_index(vault))
    assert len(repo3.notes()) == 1
    current = repo3.current_note(first.note.id)
    assert current is not None and current.title == "bounty hunter"

    note_files = [
        p
        for p in vault.glob("*.md")
        if p.name not in ("Plan.md", "Masterplan.md", "Timeline.md", "_grandplan-guide.md")
    ]
    assert len(note_files) == 1  # the title edit re-rendered in place — no orphaned old-title file
    note_md = note_files[0].read_text(encoding="utf-8")
    assert "# bounty hunter" in note_md and "## History" in note_md and "edit: title" in note_md

    plan = (vault / "Plan.md").read_text(encoding="utf-8")
    assert "## What moved" in plan and "edit: title → bounty hunter" in plan


def test_capture_with_a_url_renders_a_resource_link_and_persists(tmp_path: Path) -> None:
    """PR-D end-to-end: a capture mentioning a URL produces a note whose `.md` renders it in a
    `## Resources` section, and the resource persists across a reopen + re-projection."""
    vault = tmp_path / "vault"
    repo = JsonlNoteRepository(_index(vault))
    originals = JsonlOriginalStore(_inbox(vault))

    result = approve(
        _start("check the repo https://github.com/me/proj for the API", repo, originals),
        repo=repo,
        vault=MarkdownVaultWriter(vault),
    )
    assert not isinstance(result, (StatusUpdateResult, EditResult))  # a real new note
    note_md = result.path.read_text(encoding="utf-8")
    assert "## Resources" in note_md
    assert "[https://github.com/me/proj](https://github.com/me/proj)" in note_md

    write_projections(repo, vault, originals=originals)  # re-render keeps the resource
    reopened = JsonlNoteRepository(_index(vault)).get_note(result.note.id)
    assert reopened is not None and reopened.resources  # persisted across the reopen


def test_attach_flow_records_a_resource_event_and_re_renders(tmp_path: Path) -> None:
    """PR-E end-to-end: attach an artifact to the note it fulfils → a `resource` event re-renders the
    note `.md` (Resources + History) and survives a reopen, with no new note."""
    from grandplan.core.attach import attach

    vault = tmp_path / "vault"
    repo = JsonlNoteRepository(_index(vault))
    originals = JsonlOriginalStore(_inbox(vault))
    first = approve(
        _start("build the resume website", repo, originals),
        repo=repo,
        vault=MarkdownVaultWriter(vault),
    )
    assert not isinstance(first, (StatusUpdateResult, EditResult))
    write_projections(repo, vault, originals=originals)

    result = attach("/Users/me/resume-final.pdf", repo=repo, embedder=HashingEmbedder())
    assert result is not None and result.note.id == first.note.id
    write_projections(repo, vault, originals=originals)

    # Reopen: the resource event persisted, derived onto the note; still one note; rendered in the .md.
    repo2 = JsonlNoteRepository(_index(vault))
    assert len(repo2.notes()) == 1
    assert any(r.ref == "/Users/me/resume-final.pdf" for r in repo2.resources_of(first.note.id))
    note_md = next(
        p
        for p in vault.glob("*.md")
        if p.name not in ("Plan.md", "Masterplan.md", "Timeline.md", "_grandplan-guide.md")
    ).read_text(encoding="utf-8")
    assert "## Resources" in note_md and "resume-final.pdf" in note_md
    assert "## History" in note_md and "+file:" in note_md  # the attach shows as progress
