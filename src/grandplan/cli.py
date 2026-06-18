"""Command-line entrypoint.

`grandplan organize <file> -o <vault>` runs the full offline core loop over a text file
(organize → embed → reconcile → write note + link related) and writes `graph.json` + `Plan.md`.
`grandplan gui -o <vault>` launches the tray GUI (Windows; needs `grandplan[windows,gui]`).

By default `organize` uses the offline deterministic baselines; `--llm` / `--embeddings` swap in a
local Ollama model and local embeddings (graceful fallback / clear error if unavailable).
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from grandplan.adapters.ollama_organizer import DEFAULT_MODEL, OllamaOrganizer
from grandplan.adapters.st_embedder import SentenceTransformerEmbedder
from grandplan.core.attach import attach
from grandplan.core.embed import HashingEmbedder
from grandplan.core.index_location import migrate_legacy_index
from grandplan.core.models import NoteStatus, Source
from grandplan.core.note_store import JsonlNoteRepository
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.pipeline import assess, commit, propose
from grandplan.core.ports import Embedder, Organizer
from grandplan.core.project import write_projections
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore, JsonlOriginalStore
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
            links=assessment.proposal.links(),
            status=(
                NoteStatus.NEEDS_REVIEW if assessment.proposal.requires_review else NoteStatus.INBOX
            ),
        )
        committed += 1

    # Pass `originals` so each note's .md is (re-)rendered from its derived state too (PR-C):
    # status/edit events show up in the note files, not just in Plan.md/graph.json.
    graph_path, plan_path = write_projections(repo, vault_dir, originals=originals)
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


def _run_organize(args: argparse.Namespace) -> int:
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


def _run_attach(args: argparse.Namespace) -> int:
    """`grandplan attach <ref> -o <vault>`: attach an artifact to the note it fulfils (PR-E)."""
    vault_dir = Path(args.vault)
    # The persistent index the GUI maintains — kept outside the (cloud-synced) vault (PR #41).
    index_root = migrate_legacy_index(vault_dir)
    repo = JsonlNoteRepository(index_root / "index.jsonl")
    originals = JsonlOriginalStore(index_root / "inbox.jsonl")
    # The query must be embedded with the SAME embedder that built the stored note embeddings.
    embedder: Embedder = SentenceTransformerEmbedder() if args.embeddings else HashingEmbedder()
    result = attach(args.ref, repo=repo, embedder=embedder, description=args.describe or None)
    if result is None:
        print(f"no note matched {args.ref!r} — try --describe to guide the match", file=sys.stderr)
        return 1
    # Re-render so the matched note's .md shows the new resource + history (PR-C/PR-D).
    write_projections(repo, vault_dir, originals=originals)
    print(f"attached {result.resource.kind.value} to '{result.note.title}': {result.resource.ref}")
    return 0


def _run_rerender(args: argparse.Namespace) -> int:
    """`grandplan rerender -o <vault>`: re-render every note from the index with the current format —
    resolves old phantom `[[id]]` links, adds type/status tags, and writes the graph colour config."""
    vault_dir = Path(args.vault)
    index_root = migrate_legacy_index(vault_dir)
    index_path = index_root / "index.jsonl"
    if not index_path.exists():
        print(f"no index found for {vault_dir} (nothing to re-render)", file=sys.stderr)
        return 1
    repo = JsonlNoteRepository(index_path)
    originals = JsonlOriginalStore(index_root / "inbox.jsonl")
    write_projections(repo, vault_dir, originals=originals)
    print(
        f"re-rendered {len(repo.notes())} note(s) in {vault_dir} (links resolved, graph coloured)"
    )
    return 0


def _missing_gui_dependency(args: argparse.Namespace) -> str | None:
    """A user-facing error if a requested optional backend isn't installed (else None).

    `--embeddings` is a hard requirement (the GUI has no fallback embedder once selected), so we
    fail fast at startup with install guidance instead of crashing on the first capture. `--llm`
    needs no check: OllamaOrganizer degrades to the offline baseline if Ollama is unavailable.
    """
    if args.embeddings and importlib.util.find_spec("sentence_transformers") is None:
        return (
            "error: --embeddings needs sentence-transformers — "
            "`pip install grandplan[embeddings]` "
            "(or drop --embeddings to use the offline baseline embedder)"
        )
    return None


def _run_gui(args: argparse.Namespace) -> int:
    missing = _missing_gui_dependency(args)
    if missing:
        print(missing, file=sys.stderr)
        return 1
    try:
        from grandplan.app.gui import run_app

        return run_app(
            vault_dir=Path(args.vault),
            use_llm=args.llm,
            use_embeddings=args.embeddings,
            model=args.model,
        )
    except ImportError as exc:
        print(
            f"error: the GUI needs PySide6 — `pip install grandplan[windows,gui]` ({exc})",
            file=sys.stderr,
        )
        return 1


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
    organize.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name for --llm")

    attach_cmd = subparsers.add_parser(
        "attach", help="Attach an artifact (file path or URL) to the note it fulfils."
    )
    attach_cmd.add_argument("ref", help="a file path or URL to attach")
    attach_cmd.add_argument("-o", "--vault", required=True, help="the vault directory")
    attach_cmd.add_argument(
        "--describe", default="", help="text to match the note on (default: words from the ref)"
    )
    attach_cmd.add_argument(
        "--embeddings",
        action="store_true",
        help="match with sentence-transformer embeddings (use if the vault was built with them)",
    )

    rerender = subparsers.add_parser(
        "rerender", help="Re-render all notes (fix old links, add tags, colour the graph)."
    )
    rerender.add_argument("-o", "--vault", required=True, help="the vault directory")

    gui = subparsers.add_parser(
        "gui", help="Launch the tray GUI (Windows; needs the windows,gui extras)."
    )
    gui.add_argument("-o", "--vault", required=True, help="vault directory to write notes into")
    gui.add_argument("--llm", action="store_true", help="organize with a local Ollama model")
    gui.add_argument(
        "--embeddings", action="store_true", help="use local sentence-transformer embeddings"
    )
    gui.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name for --llm")

    args = parser.parse_args(argv)
    if args.command == "gui":
        return _run_gui(args)
    if args.command == "attach":
        return _run_attach(args)
    if args.command == "rerender":
        return _run_rerender(args)
    return _run_organize(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
