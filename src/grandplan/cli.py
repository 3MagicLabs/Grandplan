"""Command-line entrypoint: organize a text file into an Obsidian vault + graph + plan.

Splits a (possibly messy) text file into paragraph-sized captures and runs the full core loop
on each — organize → embed → reconcile (auto-skipping near-duplicates) → write a note + link
related notes — then writes `graph.json` and `Plan.md` into the vault.

By default it uses the fully-offline deterministic baselines. `--llm` swaps in a local Ollama
model for organization (falls back to the baseline if Ollama isn't available); `--embeddings`
swaps in local sentence-transformer embeddings (requires the `embeddings` extra). The Windows
global-capture / GUI adapters are separate (see docs/WINDOWS.md).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from grandplan.adapters.ollama_organizer import OllamaOrganizer
from grandplan.adapters.st_embedder import SentenceTransformerEmbedder
from grandplan.core.embed import HashingEmbedder
from grandplan.core.graph import export_graph
from grandplan.core.models import Source
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.pipeline import assess, commit, propose
from grandplan.core.planner import write_plan
from grandplan.core.ports import Embedder, Organizer
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


def organize_text(
    text: str,
    *,
    source: Source,
    created: str,
    vault_dir: Path,
    organizer: Organizer | None = None,
    embedder: Embedder | None = None,
) -> RunSummary:
    """Run the full core loop over each paragraph of `text` into `vault_dir`."""
    active_organizer: Organizer = organizer or HeuristicOrganizer()
    active_embedder: Embedder = embedder or HashingEmbedder()
    originals = InMemoryOriginalStore()
    repo = InMemoryNoteRepository()
    vault = MarkdownVaultWriter(vault_dir)
    reconciler = SimilarityReconciler()

    committed = 0
    skipped = 0
    for chunk in _paragraphs(text):
        original, proposed = propose(
            chunk, source, created, organizer=active_organizer, originals=originals
        )
        assessment = assess(proposed, embedder=active_embedder, repo=repo, reconciler=reconciler)
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
    organize.add_argument(
        "--llm",
        action="store_true",
        help="organize with a local Ollama model (falls back to the baseline if unavailable)",
    )
    organize.add_argument(
        "--embeddings",
        action="store_true",
        help="use local sentence-transformer embeddings (needs the 'embeddings' extra)",
    )
    organize.add_argument("--model", default="llama3.2:3b", help="Ollama model name for --llm")
    args = parser.parse_args(argv)

    organizer: Organizer | None = OllamaOrganizer(model=args.model) if args.llm else None
    embedder: Embedder | None = SentenceTransformerEmbedder() if args.embeddings else None

    title = "stdin" if args.input == "-" else Path(args.input).name
    try:
        summary = organize_text(
            _read_input(args.input),
            source=Source(app="cli", title=title),
            created=datetime.now(timezone.utc).isoformat(),
            vault_dir=Path(args.vault),
            organizer=organizer,
            embedder=embedder,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"organized {summary.notes} note(s); skipped {summary.skipped_duplicates} duplicate(s)")
    print(f"vault: {summary.vault_dir}")
    print(f"graph: {summary.graph_path}")
    print(f"plan:  {summary.plan_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
