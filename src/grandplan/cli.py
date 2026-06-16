"""Command-line entrypoint: organize a text file into an Obsidian vault + graph + plan.

Splits a (possibly messy) text file into paragraph-sized captures and runs the full offline
core loop on each — organize → embed → reconcile (auto-skipping near-duplicates) → write a
note + link related notes — then writes `graph.json` and `Plan.md` into the vault. Fully
offline and deterministic. The Windows global-capture / GUI / local-LLM adapters are separate
(see SPEC §6 / ADR-0003); this CLI exercises the same core they will drive.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from grandplan.core.embed import HashingEmbedder
from grandplan.core.graph import export_graph
from grandplan.core.models import Source
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.pipeline import assess, commit, propose
from grandplan.core.planner import write_plan
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore
from grandplan.core.vault import MarkdownVaultWriter

_PARAGRAPH = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class RunSummary:
    """Outcome of organizing a text into a vault."""

    notes: int
    skipped_duplicates: int
    vault_dir: Path
    graph_path: Path
    plan_path: Path


def organize_text(text: str, *, source: Source, created: str, vault_dir: Path) -> RunSummary:
    """Run the full offline core loop over each paragraph of `text` into `vault_dir`."""
    originals = InMemoryOriginalStore()
    repo = InMemoryNoteRepository()
    vault = MarkdownVaultWriter(vault_dir)
    organizer = HeuristicOrganizer()
    embedder = HashingEmbedder()
    reconciler = SimilarityReconciler()

    committed = 0
    skipped = 0
    for chunk in _paragraphs(text):
        original, proposed = propose(
            chunk, source, created, organizer=organizer, originals=originals
        )
        assessment = assess(proposed, embedder=embedder, repo=repo, reconciler=reconciler)
        if assessment.proposal.is_probable_duplicate:
            skipped += 1
            continue
        commit(
            original,
            proposed,
            assessment,
            repo=repo,
            vault=vault,
            link_to=assessment.proposal.related_notes,
        )
        committed += 1

    vault_dir.mkdir(parents=True, exist_ok=True)
    graph_path = export_graph(repo, vault_dir / "graph.json")
    plan_path = write_plan(repo, vault_dir / "Plan.md")
    return RunSummary(
        notes=committed,
        skipped_duplicates=skipped,
        vault_dir=vault_dir,
        graph_path=graph_path,
        plan_path=plan_path,
    )


def _paragraphs(text: str) -> list[str]:
    return [chunk.strip() for chunk in _PARAGRAPH.split(text) if chunk.strip()]


def _read_input(source_arg: str) -> str:
    if source_arg == "-":
        return sys.stdin.read()
    return Path(source_arg).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="grandplan", description="Offline knowledge organizer.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    organize = subparsers.add_parser("organize", help="Organize a text file into a vault.")
    organize.add_argument("input", help="path to a text file, or - for stdin")
    organize.add_argument("-o", "--vault", required=True, help="output vault directory")
    args = parser.parse_args(argv)

    text = _read_input(args.input)
    title = "stdin" if args.input == "-" else Path(args.input).name
    summary = organize_text(
        text,
        source=Source(app="cli", title=title),
        created=datetime.now(timezone.utc).isoformat(),
        vault_dir=Path(args.vault),
    )
    print(f"organized {summary.notes} note(s); skipped {summary.skipped_duplicates} duplicate(s)")
    print(f"vault: {summary.vault_dir}")
    print(f"graph: {summary.graph_path}")
    print(f"plan:  {summary.plan_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
