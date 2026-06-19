"""Command-line entrypoint.

`grandplan organize <file> -o <vault>` runs the full offline core loop over a text file
(organize → embed → reconcile → place into the graph → write note + links) and writes
`graph.json` + `Plan.md` plus a diagnostic report. `grandplan gui -o <vault>` launches the tray
GUI (Windows; needs `grandplan[windows,gui]`).

The local Ollama model is the **default** organizer/placer; `--no-llm` opts into the deterministic
offline baselines; `--embeddings` swaps in local embeddings. With the model selected it FAILS LOUD
if Ollama is unavailable (no silent keyword output). Other subcommands: `regenerate` (rebuild a
vault from its captured originals), `doctor` (health report), `attach`, `rerender`.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from grandplan.adapters.ollama_organizer import (
    DEFAULT_MODEL,
    OllamaOrganizer,
    OrganizerUnavailable,
)
from grandplan.adapters.llm_placer import LlmPlacer
from grandplan.adapters.st_embedder import SentenceTransformerEmbedder
from grandplan.core.attach import attach
from grandplan.core.calendar import is_scheduled, to_ics
from grandplan.core.embed import HashingEmbedder
from grandplan.core.index_location import migrate_legacy_index
from grandplan.core.models import NoteStatus, Source
from grandplan.core.note_store import JsonlNoteRepository
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.pipeline import assess, commit, propose
from grandplan.core.placement import HeuristicPlacer, Placer, record_placement
from grandplan.core.ports import Embedder, Organizer
from grandplan.core.project import remove_phantom_link_files, write_projections
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.report import RunReport, build_run_report, render_report
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
    report: RunReport | None = None  # diagnostic snapshot (notes/edges/quality) for the run output


def organize_text(
    text: str,
    *,
    source: Source,
    created: str,
    vault_dir: Path,
    organizer: Organizer | None = None,
    embedder: Embedder | None = None,
    placer: Placer | None = None,
) -> RunSummary:
    """Run the full core loop over each paragraph of `text` into `vault_dir`.

    `placer` (PR-G) proposes structural edges (`part_of`/`depends_on`) for each note against the
    notes already committed; None = no placement (the default keeps the core tests hermetic — the
    CLI arg layer supplies the real placer)."""
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
        # Placement runs BEFORE commit so the new note isn't a candidate for its own parent.
        placement = (
            placer.place(proposed, assessment.embedding, repo) if placer is not None else None
        )
        result = commit(
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
        record_placement(repo, placement, result.note.id)
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
        report=build_run_report(repo, originals),
    )


def _make_placer(use_llm: bool, model: str) -> Placer:
    """The structural placer for the run: LLM under the default, deterministic heuristic for --no-llm."""
    return LlmPlacer(model=model) if use_llm else HeuristicPlacer()


def _paragraphs(text: str) -> list[str]:
    return [chunk.strip() for chunk in _PARAGRAPH.split(text) if chunk.strip()]


def _read_input(source_arg: str) -> str:
    if source_arg == "-":
        return sys.stdin.read()
    return Path(source_arg).read_text(encoding="utf-8")


def _run_organize(args: argparse.Namespace) -> int:
    # PR-F (RC1): the local model is the DEFAULT — `--no-llm` opts into the offline baseline. With
    # the LLM, `require=True` makes a missing/unreachable model fail loud (no silent keyword garbage).
    use_llm = not args.no_llm
    organizer: Organizer | None = (
        OllamaOrganizer(model=args.model, require=True) if use_llm else None
    )
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
            placer=_make_placer(use_llm, args.model),  # PR-G: structural part_of/depends_on edges
        )
    except OrganizerUnavailable as exc:
        print(f"error: {exc}\nnothing was written.", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"organized {summary.notes} note(s); skipped {summary.skipped_duplicates} duplicate(s)")
    print(f"vault: {summary.vault_dir}")
    print(f"graph: {summary.graph_path}")
    print(f"plan:  {summary.plan_path}")
    if summary.report is not None:
        print(render_report(summary.report, organizer_label=_organizer_label(use_llm, args.model)))
    return 0


def _organizer_label(use_llm: bool, model: str) -> str:
    return f"local model ({model})" if use_llm else "offline keyword baseline (--no-llm)"


def _organize_originals(
    originals: JsonlOriginalStore,
    *,
    repo: JsonlNoteRepository,
    organizer: Organizer,
    embedder: Embedder,
    vault: MarkdownVaultWriter,
    placer: Placer,
) -> tuple[int, int]:
    """Re-run organize→assess→commit over already-captured originals (regenerate). Returns
    (committed, skipped-as-duplicate). The originals are never mutated (read-only here)."""
    reconciler = SimilarityReconciler()
    committed = skipped = 0
    for original in originals.all():
        proposed = organizer.organize(original)  # may raise OrganizerUnavailable (require=True)
        assessment = assess(proposed, embedder=embedder, repo=repo, reconciler=reconciler)
        if assessment.proposal.is_probable_duplicate:
            skipped += 1
            continue
        placement = placer.place(proposed, assessment.embedding, repo)  # before commit (no self)
        result = commit(
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
        record_placement(repo, placement, result.note.id)
        committed += 1
    return committed, skipped


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
    swept = remove_phantom_link_files(vault_dir)  # empty `<id>.md` stubs from old phantom links
    write_projections(repo, vault_dir, originals=originals)
    print(
        f"re-rendered {len(repo.notes())} note(s) in {vault_dir} "
        f"(links resolved, graph coloured, {swept} phantom stub(s) removed)"
    )
    return 0


def _run_regenerate(args: argparse.Namespace) -> int:
    """`grandplan regenerate -o <vault>`: rebuild the derived notes/edges from the lossless
    `inbox.jsonl` originals through the CURRENT organize pipeline — so heuristic-era notes become
    real LLM notes (RC4). The originals are never touched; the old index is backed up first.

    Atomic + fail-safe: rebuilds into a temp index and only swaps it in on success, so a fail-loud
    LLM (require=True) or any error leaves the existing index intact.
    """
    use_llm = not args.no_llm
    vault_dir = Path(args.vault)
    index_root = migrate_legacy_index(vault_dir)
    index_path = index_root / "index.jsonl"
    originals = JsonlOriginalStore(index_root / "inbox.jsonl")
    if not originals.all():
        print(f"no captured originals under {index_root} (nothing to regenerate)", file=sys.stderr)
        return 1

    organizer: Organizer = (
        OllamaOrganizer(model=args.model, require=True) if use_llm else HeuristicOrganizer()
    )
    embedder: Embedder = SentenceTransformerEmbedder() if args.embeddings else HashingEmbedder()

    temp_path = index_root / "index.regen.jsonl"
    temp_path.unlink(missing_ok=True)  # start clean (e.g. after an earlier interrupted run)
    repo = JsonlNoteRepository(temp_path)
    vault = MarkdownVaultWriter(vault_dir)
    try:
        committed, skipped = _organize_originals(
            originals,
            repo=repo,
            organizer=organizer,
            embedder=embedder,
            vault=vault,
            placer=_make_placer(use_llm, args.model),  # PR-G: structural edges on regenerate too
        )
    except OrganizerUnavailable as exc:
        temp_path.unlink(missing_ok=True)  # leave the existing index untouched
        print(
            f"error: {exc}\nregenerate aborted; your existing vault is unchanged.", file=sys.stderr
        )
        return 1

    # Success: back up the old index, then atomically swap the rebuilt one in.
    if index_path.exists():
        index_path.replace(index_path.with_suffix(".jsonl.bak"))
    temp_path.replace(index_path)
    # Re-render every note + the projections from the fresh index (resolves links, colours the graph).
    remove_phantom_link_files(vault_dir)
    # regenerate re-organizes from scratch, so it deliberately REPLACES note bodies (no preserve).
    write_projections(
        JsonlNoteRepository(index_path),
        vault_dir,
        originals=originals,
        preserve_external_body=False,
    )
    print(
        f"regenerated {committed} note(s) from {len(originals.all())} original(s); "
        f"skipped {skipped} duplicate(s). Old index → index.jsonl.bak"
    )
    print(
        render_report(
            build_run_report(repo, originals), organizer_label=_organizer_label(use_llm, args.model)
        )
    )
    return 0


def _run_calendar(args: argparse.Namespace) -> int:
    """`grandplan calendar -o <vault> [--out PATH]`: export dated notes to an .ics calendar feed.

    Local + offline (zero egress): point your calendar app at the file as a subscription; re-run to
    refresh it. Read-only over the vault — only writes the `.ics`.
    """
    vault_dir = Path(args.vault)
    index_root = migrate_legacy_index(vault_dir)
    index_path = index_root / "index.jsonl"
    if not index_path.exists():
        print(f"no index found for {vault_dir} (nothing to export)", file=sys.stderr)
        return 1
    repo = JsonlNoteRepository(index_path)
    notes = repo.current_notes()
    out = Path(args.out) if args.out else vault_dir / "grandplan.ics"
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_ics(notes, dtstamp=dtstamp), encoding="utf-8")
    scheduled = sum(1 for note in notes if is_scheduled(note))
    print(f"wrote {scheduled} event(s) to {out}")
    if scheduled == 0:
        print("(no notes have a `due` date yet — add due dates to see events)")
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    """`grandplan doctor -o <vault>`: inspect an existing vault and print the health report —
    note/edge/horizon counts, structural-vs-semantic edges, low-quality notes (QAS-8). Read-only."""
    vault_dir = Path(args.vault)
    index_root = migrate_legacy_index(vault_dir)
    index_path = index_root / "index.jsonl"
    if not index_path.exists():
        print(f"no index found for {vault_dir} (nothing to diagnose)", file=sys.stderr)
        return 1
    repo = JsonlNoteRepository(index_path)
    originals = JsonlOriginalStore(index_root / "inbox.jsonl")
    print(render_report(build_run_report(repo, originals), organizer_label="(existing vault)"))
    return 0


def _run_mcp(args: argparse.Namespace) -> int:
    """`grandplan mcp -o <vault> [--embeddings]`: serve the vault to AI agents over MCP/stdio.

    Read-only + offline (stdio transport, no sockets). Needs the optional `mcp` extra.
    """
    vault_dir = Path(args.vault)
    index_root = migrate_legacy_index(vault_dir)
    index_path = index_root / "index.jsonl"
    if not index_path.exists():
        print(f"no index found for {vault_dir} (nothing to serve)", file=sys.stderr)
        return 1
    repo = JsonlNoteRepository(index_path)
    originals = JsonlOriginalStore(index_root / "inbox.jsonl")
    # The query embedder must match the one the vault was built with so search ranks correctly.
    embedder: Embedder = SentenceTransformerEmbedder() if args.embeddings else HashingEmbedder()
    try:
        from grandplan.adapters.mcp_server import run_stdio_server
        from grandplan.core.query import VaultQuery

        run_stdio_server(VaultQuery(repo=repo, originals=originals, embedder=embedder))
    except (ImportError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
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
            use_llm=not args.no_llm,  # PR-F: the local model is the default; --no-llm opts out
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
        "--no-llm",
        action="store_true",
        help="use the offline keyword baseline instead of the local model (lower quality)",
    )
    organize.add_argument(
        "--llm",
        action="store_true",
        help="(default) organize with the local Ollama model — kept for back-compat; now the default",
    )
    organize.add_argument(
        "--embeddings",
        action="store_true",
        help="use local sentence-transformer embeddings (needs the 'embeddings' extra)",
    )
    organize.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name (default LLM)")

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

    regenerate = subparsers.add_parser(
        "regenerate",
        help="Re-organize the whole vault from the captured originals (heuristic→LLM quality).",
    )
    regenerate.add_argument("-o", "--vault", required=True, help="the vault directory")
    regenerate.add_argument(
        "--no-llm", action="store_true", help="re-organize with the offline keyword baseline"
    )
    regenerate.add_argument(
        "--embeddings", action="store_true", help="use sentence-transformer embeddings"
    )
    regenerate.add_argument(
        "--model", default=DEFAULT_MODEL, help="Ollama model name (default LLM)"
    )

    doctor = subparsers.add_parser(
        "doctor", help="Diagnose an existing vault (note/edge/quality report); read-only."
    )
    doctor.add_argument("-o", "--vault", required=True, help="the vault directory")

    calendar = subparsers.add_parser(
        "calendar", help="Export dated notes to an .ics calendar feed (offline; subscribe to it)."
    )
    calendar.add_argument("-o", "--vault", required=True, help="the vault directory")
    calendar.add_argument(
        "--out", default="", help="output .ics path (default: <vault>/grandplan.ics)"
    )

    mcp_cmd = subparsers.add_parser(
        "mcp",
        help="Serve the vault to AI agents over MCP/stdio (read-only; needs the 'mcp' extra).",
    )
    mcp_cmd.add_argument("-o", "--vault", required=True, help="the vault directory")
    mcp_cmd.add_argument(
        "--embeddings", action="store_true", help="use sentence-transformer embeddings for search"
    )

    gui = subparsers.add_parser(
        "gui", help="Launch the tray GUI (Windows; needs the windows,gui extras)."
    )
    gui.add_argument("-o", "--vault", required=True, help="vault directory to write notes into")
    gui.add_argument(
        "--no-llm", action="store_true", help="use the offline keyword baseline (lower quality)"
    )
    gui.add_argument(
        "--llm", action="store_true", help="(default) organize with the local Ollama model"
    )
    gui.add_argument(
        "--embeddings", action="store_true", help="use local sentence-transformer embeddings"
    )
    gui.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name (default LLM)")

    args = parser.parse_args(argv)
    if args.command == "gui":
        return _run_gui(args)
    if args.command == "attach":
        return _run_attach(args)
    if args.command == "rerender":
        return _run_rerender(args)
    if args.command == "regenerate":
        return _run_regenerate(args)
    if args.command == "doctor":
        return _run_doctor(args)
    if args.command == "calendar":
        return _run_calendar(args)
    if args.command == "mcp":
        return _run_mcp(args)
    return _run_organize(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
