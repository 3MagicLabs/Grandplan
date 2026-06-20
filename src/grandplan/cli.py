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
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from grandplan.adapters.ollama_organizer import (
    DEFAULT_MODEL,
    OllamaOrganizer,
    OrganizerUnavailable,
)
from grandplan.adapters.llm_contextual_reconciler import LlmContextualReconciler
from grandplan.adapters.llm_placer import LlmPlacer
from grandplan.adapters.st_embedder import SentenceTransformerEmbedder
from grandplan.core.attach import attach
from grandplan.core.calendar import is_scheduled, to_ics
from grandplan.core.embed import HashingEmbedder
from grandplan.core.index_location import index_dir, migrate_legacy_index
from grandplan.core.models import NoteEvent, NoteStatus, Source
from grandplan.core.note_store import JsonlNoteRepository
from grandplan.core.organize import HeuristicOrganizer
from grandplan.adapters.llm_entity_extractor import LlmEntityExtractor
from grandplan.core.entities import (
    EntityExtractor,
    HeuristicEntityExtractor,
    materialize_entities,
)
from grandplan.core.pipeline import assess, commit, propose
from grandplan.core.placement import HeuristicPlacer, Placer, record_placement
from grandplan.core.ports import Embedder, NoteRepository, Organizer
from grandplan.core.project import remove_phantom_link_files, write_projections
from grandplan.core.reconcile import Reconciler, SimilarityReconciler
from grandplan.adapters.folder_watch import scan_folder
from grandplan.core.directive import Directive, JsonlDirectiveStore, resolve_instruction
from grandplan.core.export import to_csv, to_markdown_tasks, to_todoist_csv
from grandplan.core.render import MarkdownReportRenderer
from grandplan.core.report import RunReport, build_run_report, render_report
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore, JsonlOriginalStore, OriginalStore
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
    reconciler: Reconciler | None = None,
    entity_extractor: EntityExtractor | None = None,
    repo: NoteRepository | None = None,
    originals: OriginalStore | None = None,
) -> RunSummary:
    """Run the full core loop over each paragraph of `text` into `vault_dir`.

    `placer` (PR-G) proposes structural edges (`part_of`/`depends_on`) for each note against the
    notes already committed; `reconciler` decides how each note relates to existing ones;
    `entity_extractor` (ROADMAP 3) surfaces people/org `entity` nodes + `involves` edges from each
    note. None for any keeps the deterministic baseline (the CLI arg layer supplies LLM-backed ones).

    `repo`/`originals` let the caller inject **persistent** stores so the captured notes + originals
    land in the queryable index (not just the Obsidian vault) — the CLI passes the Jsonl stores so
    `doctor`/`report`/`export`/`mcp` see what `organize` produced. They default to in-memory (a
    one-shot, vault-only run). Both are append-only + idempotent, so re-organizing the same text is a
    no-op."""
    active_organizer: Organizer = organizer or HeuristicOrganizer()
    active_embedder: Embedder = embedder or HashingEmbedder()
    active_entity_extractor: EntityExtractor = entity_extractor or HeuristicEntityExtractor()
    originals = originals if originals is not None else InMemoryOriginalStore()
    repo = repo if repo is not None else InMemoryNoteRepository()
    vault = MarkdownVaultWriter(vault_dir)
    active_reconciler: Reconciler = reconciler or SimilarityReconciler()

    committed = 0
    skipped = 0
    for chunk in _paragraphs(text):
        original, proposed = propose(
            chunk, source, created, organizer=active_organizer, originals=originals
        )
        assessment = assess(
            proposed, embedder=active_embedder, repo=repo, reconciler=active_reconciler
        )
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
        # ROADMAP 3: surface people/org entities from the verbatim capture as `entity` nodes joined
        # by `involves` edges — append-only, idempotent, never mutates the note.
        materialize_entities(
            repo,
            originals,
            active_embedder,
            result.note.id,
            active_entity_extractor.extract(chunk),
        )
        committed += 1

    # Pass `originals` so each note's .md is (re-)rendered from its derived state too (PR-C):
    # status/edit events show up in the note files, not just in Plan.md/graph.json.
    graph_path, plan_path = write_projections(
        repo, vault_dir, originals=originals, today=datetime.now(timezone.utc).date()
    )
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


def _make_entity_extractor(use_llm: bool, model: str) -> EntityExtractor:
    """The entity extractor for the run: LLM (unioned with heuristic) by default, heuristic for --no-llm."""
    return LlmEntityExtractor(model=model) if use_llm else HeuristicEntityExtractor()


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
    # Persist into the queryable index (not just the Obsidian vault), so doctor/report/export/calendar/
    # mcp see what organize produced — the persistent stores the GUI capture flow also writes to.
    index_root = migrate_legacy_index(Path(args.vault))
    try:
        summary = organize_text(
            _read_input(args.input),
            source=Source(app="cli", title=title),
            created=datetime.now(timezone.utc).isoformat(),
            vault_dir=Path(args.vault),
            organizer=organizer,
            embedder=embedder,
            placer=_make_placer(use_llm, args.model),  # PR-G: structural part_of/depends_on edges
            entity_extractor=_make_entity_extractor(use_llm, args.model),  # ROADMAP 3: entities
            reconciler=(
                LlmContextualReconciler(model=args.model) if use_llm else None
            ),  # neighborhood-aware relationship classification
            repo=JsonlNoteRepository(index_root / "index.jsonl"),
            originals=JsonlOriginalStore(index_root / "inbox.jsonl"),
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
    entity_extractor: EntityExtractor,
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
        materialize_entities(
            repo, originals, embedder, result.note.id, entity_extractor.extract(original.text)
        )
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
    write_projections(repo, vault_dir, originals=originals, today=datetime.now(timezone.utc).date())
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
    # reconcile_deletions: notes the user removed from the vault are tombstoned, not resurrected.
    write_projections(
        repo,
        vault_dir,
        originals=originals,
        reconcile_deletions=True,
        today=datetime.now(timezone.utc).date(),
    )
    print(
        f"re-rendered {len(repo.notes())} note(s) in {vault_dir} "
        f"(links resolved, graph coloured, {swept} phantom stub(s) removed)"
    )
    return 0


def _replay_history(events: tuple[NoteEvent, ...], repo: JsonlNoteRepository) -> tuple[int, int]:
    """Replay status/edit/resource/deletion events onto notes that still exist (preserved, dropped).

    A from-scratch rebuild re-creates notes; their content-addressed ids are stable iff the organized
    (title, body, type) is unchanged. Events for a surviving id are re-applied (each is idempotent +
    orphan-guarded); events whose note id no longer exists are counted as dropped. The `note`/`edge`
    creation records are not replayed — the rebuild already produced them.
    """
    preserved = dropped = 0
    for event in events:
        if repo.current_note(event.note_id) is None and event.kind != "deleted":
            dropped += 1
            continue
        if event.kind == "status" and event.status is not None:
            repo.set_status(event.note_id, event.status, at=event.at)
        elif event.kind == "edit" and event.edit is not None:
            repo.record_edit(event.note_id, event.edit, at=event.at)
        elif event.kind == "resource" and event.resource is not None:
            repo.add_resource(event.note_id, event.resource, at=event.at)
        elif event.kind == "deleted":
            repo.delete_note(event.note_id, at=event.at)
        preserved += 1
    return preserved, dropped


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

    # Capture the prior event history BEFORE the rebuild, so --keep-history can replay it afterward.
    old_events: tuple[NoteEvent, ...] = (
        JsonlNoteRepository(index_path).events()
        if args.keep_history and index_path.exists()
        else ()
    )

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
            entity_extractor=_make_entity_extractor(use_llm, args.model),  # ROADMAP 3: entities
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
    # --keep-history: replay the prior status/edit/resource/deletion events onto surviving notes.
    final_repo = JsonlNoteRepository(index_path)
    preserved = dropped = 0
    if old_events:
        preserved, dropped = _replay_history(old_events, final_repo)
    # Re-render every note + the projections from the fresh index (resolves links, colours the graph).
    remove_phantom_link_files(vault_dir)
    # regenerate re-organizes from scratch, so it deliberately REPLACES note bodies (no preserve).
    write_projections(
        final_repo,
        vault_dir,
        originals=originals,
        preserve_external_body=False,
        today=datetime.now(timezone.utc).date(),
    )
    history_note = (
        f" Replayed {preserved} history event(s)"
        + (f", dropped {dropped}" if dropped else "")
        + "."
        if args.keep_history
        else ""
    )
    print(
        f"regenerated {committed} note(s) from {len(originals.all())} original(s); "
        f"skipped {skipped} duplicate(s). Old index → index.jsonl.bak.{history_note}"
    )
    print(
        render_report(
            build_run_report(final_repo, originals),
            organizer_label=_organizer_label(use_llm, args.model),
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


def _is_dangerous_delete_target(path: Path) -> bool:
    """True if deleting `path` would be obviously catastrophic (a filesystem/drive root or $HOME).

    A safety net for `reset` (which the shell's careful-mode can't guard): never `rmtree` a root or
    the user's home, even if the user points `-o` at one.
    """
    resolved = path.expanduser()
    try:
        resolved = resolved.resolve()
    except OSError:  # pragma: no cover - defensive; resolve rarely raises
        pass
    if resolved.parent == resolved:  # filesystem / drive root (e.g. `/` or `C:\`)
        return True
    try:
        return resolved == Path.home().resolve()
    except OSError:  # pragma: no cover - defensive
        return False


def _run_reset(args: argparse.Namespace) -> int:
    """`grandplan reset -o <vault> [--yes] [--keep-originals]`: wipe a vault back to empty.

    Deletes the Obsidian vault folder AND grandplan's internal index (notes/edges/inbox/directives).
    `--keep-originals` keeps the lossless captures (so `grandplan regenerate` can rebuild) and removes
    only the derived notes/index + the vault folder. Asks for confirmation unless `--yes`.
    """
    vault_dir = Path(args.vault)
    index_root = index_dir(vault_dir)  # locate (don't migrate — we're deleting)
    if _is_dangerous_delete_target(vault_dir) or _is_dangerous_delete_target(index_root):
        print(
            f"error: refusing to reset {vault_dir} — that path looks like a root or home directory.",
            file=sys.stderr,
        )
        return 1

    note_count = (
        len(JsonlNoteRepository(index_root / "index.jsonl").notes())
        if (index_root / "index.jsonl").exists()
        else 0
    )
    targets = [t for t in (vault_dir, index_root) if t.exists()]
    if not targets and note_count == 0:
        print(f"nothing to reset — no vault or index found for {vault_dir}")
        return 0

    if not args.yes:
        print(f"This will permanently reset '{vault_dir}':", file=sys.stderr)
        if vault_dir.exists():
            print(f"  - delete the vault folder {vault_dir}", file=sys.stderr)
        print(
            f"  - delete the index ({note_count} note(s)) at {index_root}"
            + ("  [keeping your captured originals]" if args.keep_originals else ""),
            file=sys.stderr,
        )
        if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("aborted — nothing was deleted.", file=sys.stderr)
            return 1

    if vault_dir.exists():
        shutil.rmtree(vault_dir)
    if args.keep_originals:
        # Keep inbox.jsonl (the lossless captures); drop the derived index + directives + backups.
        for name in ("index.jsonl", "index.jsonl.bak", "directives.jsonl"):
            (index_root / name).unlink(missing_ok=True)
    elif index_root.exists():
        shutil.rmtree(index_root)
    kept = (
        " (captured originals kept — run `grandplan regenerate` to rebuild)"
        if args.keep_originals
        else ""
    )
    print(f"reset complete: {vault_dir} is now empty.{kept}")
    return 0


def _run_report(args: argparse.Namespace) -> int:
    """`grandplan report -o <vault> [--out PATH] [--title T]`: render a stand-alone Markdown report.

    A deliverable (not a live projection): one self-contained document — summary, top priorities,
    blocked, schedule, hierarchy by horizon, open questions, graph health. Read-only over the vault;
    writes the report file (default `<vault>/report.md`) and echoes it to stdout when `--out -`.
    """
    vault_dir = Path(args.vault)
    index_root = migrate_legacy_index(vault_dir)
    index_path = index_root / "index.jsonl"
    if not index_path.exists():
        print(f"no index found for {vault_dir} (nothing to report)", file=sys.stderr)
        return 1
    repo = JsonlNoteRepository(index_path)
    originals = JsonlOriginalStore(index_root / "inbox.jsonl")
    renderer = MarkdownReportRenderer(
        title=args.title or "grandplan report",
        created=datetime.now(timezone.utc).date().isoformat(),
    )
    text = renderer.render(repo, originals)
    if args.out == "-":
        print(text)
        return 0
    out = Path(args.out) if args.out else vault_dir / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote report to {out}")
    return 0


def _run_export(args: argparse.Namespace) -> int:
    """`grandplan export -o <vault> --format tasks|csv [--out PATH]`: export to another tool's format.

    Local + offline (zero egress). `tasks` → a Markdown checklist (Obsidian Tasks / GitHub style);
    `csv` → one row per note. Read-only over the vault; writes the export file (or stdout with `-`).
    """
    vault_dir = Path(args.vault)
    index_root = migrate_legacy_index(vault_dir)
    index_path = index_root / "index.jsonl"
    if not index_path.exists():
        print(f"no index found for {vault_dir} (nothing to export)", file=sys.stderr)
        return 1
    repo = JsonlNoteRepository(index_path)
    notes = repo.current_notes()
    if args.format == "csv":
        text, default_name = to_csv(notes), "export.csv"
    elif args.format == "todoist":
        text, default_name = to_todoist_csv(notes), "todoist.csv"
    else:
        text, default_name = to_markdown_tasks(notes), "tasks.md"
    if args.out == "-":
        print(text)
        return 0
    out = Path(args.out) if args.out else vault_dir / default_name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {args.format} export to {out}")
    return 0


def _run_directive(args: argparse.Namespace) -> int:
    """`grandplan directive add|list -o <vault>`: queue / inspect agent intake directives.

    `add` enqueues a "content + instruction" directive (from `--prompt` or a `--playbook`) an agent
    later fulfils over MCP; `list` shows pending ones. Append-only + offline. The eventual phone→agent
    transport simply calls `add`; the agent reads them via `grandplan mcp --directives`.
    """
    vault_dir = Path(args.vault)
    index_root = migrate_legacy_index(vault_dir)
    store = JsonlDirectiveStore(index_root / "directives.jsonl")
    if args.directive_command == "list":
        pending = store.pending()
        if not pending:
            print("no pending directives")
            return 0
        for directive in pending:
            preview = directive.content[:60].replace("\n", " ")
            label = directive.playbook or "ad-hoc"
            print(f"{directive.id}  [{label}]  {preview}")
        return 0
    try:
        instruction, playbook = resolve_instruction(
            playbook=args.playbook or "", prompt=args.prompt or ""
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    content = _read_input(args.content) if args.content else sys.stdin.read()
    if not content.strip():
        print("error: no content (pass --content <file|-> or pipe text in)", file=sys.stderr)
        return 1
    directive = Directive.create(
        content,
        instruction,
        datetime.now(timezone.utc).isoformat(),
        playbook=playbook,
    )
    store.add(directive)
    print(f"queued directive {directive.id} ({playbook or 'ad-hoc'})")
    return 0


def _init_vault(vault_dir: Path, index_root: Path) -> None:
    """Scaffold a fresh, Obsidian-ready vault: graph-coloured config, guide, empty projections, and a
    workspace that opens on the graph. Idempotent + non-destructive (reuses `write_projections`)."""
    from grandplan.adapters.obsidian_open import scaffold_graph_view

    repo = JsonlNoteRepository(index_root / "index.jsonl")
    originals = JsonlOriginalStore(index_root / "inbox.jsonl")
    # Writes .obsidian/graph.json (colours) + the guide + graph.json/Plan/Masterplan/Timeline/Today.
    write_projections(repo, vault_dir, originals=originals, today=datetime.now(timezone.utc).date())
    scaffold_graph_view(vault_dir)  # workspace.json opening on the graph (only if absent)


def up_banner(
    vault: Path,
    *,
    host: str,
    port: int,
    watch_dir: Path,
    tokened: bool,
    hotkey: str | None = None,
    ai: str | None = None,
) -> str:
    """The startup summary for `grandplan up` — what's live and how to connect an agent (pure)."""
    auth = " (token required)" if tokened else ""
    lines = [
        "grandplan is up — all capture surfaces live (offline):",
        f"  vault:     {vault}",
        f"  HTTP intake:  POST http://{host}:{port}/directive{auth}",
        f"  folder watch: drop files into {watch_dir}",
    ]
    if hotkey:
        enhance = f"AI-enhanced ({ai})" if ai else "offline baseline"
        lines.append(
            f"  global hotkey: {hotkey} — select text anywhere, press it to capture [{enhance}]"
        )
    lines += [
        f"  agent:     connect with  grandplan mcp -o {vault} --write --directives",
        "  (Ctrl+C to stop)",
    ]
    return "\n".join(lines)


def _capture_to_vault(
    capturer: object,
    *,
    vault_dir: Path,
    index_root: Path,
    created: str,
    organizer: Organizer | None = None,
    placer: Placer | None = None,
    reconciler: Reconciler | None = None,
    entity_extractor: EntityExtractor | None = None,
) -> str | None:
    """Grab the current selection (via `capturer.capture()`) and organize it into the vault.

    Returns the captured text, or None when nothing is selected. The organize components are injected
    (the AI ones for `--llm`, else heuristic), so this is unit-tested with a fake capturer + heuristic
    defaults; the real Windows capturer + LLM adapters are wired in by `_run_hotkey`. Writes through
    the persistent stores so the note lands in the index + Obsidian vault.
    """
    text = capturer.capture()  # type: ignore[attr-defined]
    if not isinstance(text, str) or not text.strip():
        return None
    organize_text(
        text,
        source=Source(app="hotkey"),
        created=created,
        vault_dir=vault_dir,
        organizer=organizer,
        placer=placer or HeuristicPlacer(),  # nest the capture under a related goal/project
        reconciler=reconciler,
        entity_extractor=entity_extractor,
        repo=JsonlNoteRepository(index_root / "index.jsonl"),
        originals=JsonlOriginalStore(index_root / "inbox.jsonl"),
    )
    return text


def _run_hotkey(  # pragma: no cover - global hotkey listener + Windows selection capture (no UI)
    vault_dir: Path, index_root: Path, *, hotkey: str, use_llm: bool, model: str
) -> None:
    """Listen for the global hotkey; on each press, capture the selection and organize it (forever).

    Under `--llm`, captures are enhanced by the local model with a GRACEFUL fallback (`require=False`)
    so a hotkey never errors when Ollama is down — it just uses the offline baseline for that capture.
    """
    from grandplan.adapters.capture import make_windows_capturer, run_hotkey_listener

    capturer = make_windows_capturer()
    organizer = OllamaOrganizer(model=model, require=False) if use_llm else None
    placer: Placer = LlmPlacer(model=model) if use_llm else HeuristicPlacer()
    reconciler = LlmContextualReconciler(model=model) if use_llm else None
    entity_extractor = LlmEntityExtractor(model=model) if use_llm else None
    mode = f"AI: {model}" if use_llm else "offline baseline"

    def _on_trigger() -> None:
        print(f"capturing + organizing ({mode})…")
        text = _capture_to_vault(
            capturer,
            vault_dir=vault_dir,
            index_root=index_root,
            created=datetime.now(timezone.utc).isoformat(),
            organizer=organizer,
            placer=placer,
            reconciler=reconciler,
            entity_extractor=entity_extractor,
        )
        if text:
            print(f"  ✓ saved: {text[:60].strip()}")
        else:
            print("  (nothing was selected)")

    run_hotkey_listener(hotkey, _on_trigger)


def _run_up(args: argparse.Namespace) -> int:
    """`grandplan up -o <vault> [--init] [--open] [--folder DIR] [--host] [--port] [--token] [--dry-run]`.

    One command, all features live: starts the HTTP directive intake AND a folder-watch concurrently
    (both feeding the agent-intake loop), against the persistent index, and prints the MCP command to
    point an agent at. `--init` scaffolds a fresh vault (graph-coloured config + a workspace that opens
    on the graph); `--open` launches it in Obsidian. Binds 127.0.0.1 by default; a routable host needs
    a --token. `--dry-run` sets everything up (incl. --init/--open) without serving. Offline.
    """
    vault_dir = Path(args.vault)
    if args.host not in ("127.0.0.1", "localhost") and not args.token:
        print(
            "error: refusing to bind a non-localhost host without a --token "
            "(anyone on the network could enqueue directives)",
            file=sys.stderr,
        )
        return 1
    try:
        instruction, playbook = resolve_instruction(
            playbook=args.playbook or "capture-and-file", prompt=args.prompt or ""
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    hotkey = args.hotkey_combo if args.hotkey else None
    if hotkey and importlib.util.find_spec("pynput") is None:
        print(
            'error: --hotkey needs the input libraries — `pip install -e ".[windows]"` '
            "(pynput + pyperclip + uiautomation)",
            file=sys.stderr,
        )
        return 1
    use_llm = not args.no_llm
    if hotkey and use_llm and importlib.util.find_spec("ollama") is None:
        # Don't fail — captures still work offline — but tell the user the AI won't run as asked.
        print(
            'note: --hotkey AI enhancement needs Ollama — `pip install -e ".[llm]"` + run Ollama '
            "(`ollama pull " + args.model + "`). Captures use the offline baseline until then.",
            file=sys.stderr,
        )
    index_root = migrate_legacy_index(vault_dir)
    if args.init:
        _init_vault(vault_dir, index_root)
        print(f"initialized vault at {vault_dir}")
    store = JsonlDirectiveStore(index_root / "directives.jsonl")
    watch_dir = Path(args.folder) if args.folder else vault_dir / "_inbox"
    watch_dir.mkdir(parents=True, exist_ok=True)
    print(
        up_banner(
            vault_dir,
            host=args.host,
            port=args.port,
            watch_dir=watch_dir,
            tokened=bool(args.token),
            hotkey=hotkey,
            ai=(args.model if (hotkey and use_llm) else None),
        )
    )
    if args.open:
        from grandplan.adapters.obsidian_open import obsidian_open_uri, open_in_obsidian

        print(f"opening graph view: {obsidian_open_uri(vault_dir)}")
        open_in_obsidian(vault_dir)
    if args.dry_run:
        return 0
    _serve_all(  # pragma: no cover - launches the long-running server + watch threads
        store,
        vault_dir=vault_dir,
        index_root=index_root,
        watch_dir=watch_dir,
        host=args.host,
        port=args.port,
        token=args.token,
        instruction=instruction,
        playbook=playbook,
        interval=args.interval,
        hotkey=hotkey,
        use_llm=use_llm,
        model=args.model,
    )
    return 0


def _serve_all(  # pragma: no cover - long-running threads (HTTP serve + folder watch + hotkey)
    store: JsonlDirectiveStore,
    *,
    vault_dir: Path,
    index_root: Path,
    watch_dir: Path,
    host: str,
    port: int,
    token: str,
    instruction: str,
    playbook: str,
    interval: float,
    hotkey: str | None,
    use_llm: bool,
    model: str,
) -> None:
    """Run folder-watch (+ optional global hotkey) as daemon threads and the HTTP server foreground."""
    import threading

    from grandplan.adapters.folder_watch import watch_folder
    from grandplan.adapters.http_intake import serve_intake

    watcher = threading.Thread(
        target=watch_folder,
        kwargs={
            "folder": watch_dir,
            "store": store,
            "instruction": instruction,
            "playbook": playbook,
            "interval": interval,
            "now": lambda: datetime.now(timezone.utc).isoformat(),
        },
        daemon=True,
    )
    watcher.start()
    if hotkey:
        threading.Thread(
            target=_run_hotkey,
            args=(vault_dir, index_root),
            kwargs={"hotkey": hotkey, "use_llm": use_llm, "model": model},
            daemon=True,
        ).start()
    serve_intake(store, host=host, port=port, token=token)


def _run_watch(args: argparse.Namespace) -> int:
    """`grandplan watch -o <vault> --folder DIR [--playbook|--prompt] [--interval S] [--once]`.

    Watches `DIR` and enqueues a directive per new text/markdown file (the file-drop capture surface).
    `--once` does a single scan and exits (scriptable); otherwise it polls every `--interval` seconds.
    Offline: only reads local files.
    """
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"error: not a folder: {folder}", file=sys.stderr)
        return 1
    try:
        instruction, playbook = resolve_instruction(
            playbook=args.playbook or "", prompt=args.prompt or ""
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    index_root = migrate_legacy_index(Path(args.vault))
    store = JsonlDirectiveStore(index_root / "directives.jsonl")
    if args.once:
        ids = scan_folder(
            folder,
            store,
            created=datetime.now(timezone.utc).isoformat(),
            instruction=instruction,
            playbook=playbook,
            seen=set(),
        )
        print(f"queued {len(ids)} directive(s) from {folder}")
        return 0
    from grandplan.adapters.folder_watch import watch_folder

    watch_folder(  # pragma: no cover - delegates to the long-running poll loop
        folder,
        store,
        instruction=instruction,
        playbook=playbook,
        interval=args.interval,
        now=lambda: datetime.now(timezone.utc).isoformat(),
    )
    return 0


def _run_serve(args: argparse.Namespace) -> int:
    """`grandplan serve -o <vault> [--host H] [--port P] [--token T]`: HTTP directive intake.

    Receives `POST /directive` (`{content, playbook?, prompt?}`) and enqueues a directive an agent
    later fulfils. Binds 127.0.0.1 by default (safe); pass a routable --host + a --token to receive
    directives from your phone over the LAN/VPN. Offline: it only receives and stores locally.
    """
    vault_dir = Path(args.vault)
    index_root = migrate_legacy_index(vault_dir)
    store = JsonlDirectiveStore(index_root / "directives.jsonl")
    if args.host not in ("127.0.0.1", "localhost") and not args.token:
        print(
            "error: refusing to bind a non-localhost host without a --token "
            "(anyone on the network could enqueue directives)",
            file=sys.stderr,
        )
        return 1
    from grandplan.adapters.http_intake import serve_intake

    serve_intake(  # pragma: no cover - binds a socket; the request logic is tested via handle_intake
        store, host=args.host, port=args.port, token=args.token
    )
    return 0


def _run_mcp(args: argparse.Namespace) -> int:
    """`grandplan mcp -o <vault> [--embeddings] [--write] [--directives]`: serve the vault over MCP.

    Offline (stdio transport, no sockets). Read-only by default; `--write` exposes the append-only
    write tools; `--directives` exposes the directive intake tools (list/complete). Needs `mcp`.
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
        from grandplan.core.write import VaultWrite

        query = VaultQuery(repo=repo, originals=originals, embedder=embedder)
        write = (
            VaultWrite(repo=repo, originals=originals, embedder=embedder)
            if getattr(args, "write", False)
            else None
        )
        directives = (
            JsonlDirectiveStore(index_root / "directives.jsonl")
            if getattr(args, "directives", False)
            else None
        )
        run_stdio_server(query, write, directives)
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


# Path-bearing CLI arguments: a leading `~` is expanded to the user's home so `-o ~/MyVault` works
# (PowerShell/cmd don't expand `~` for external commands, and Path() doesn't either). `-` (stdin/
# stdout) and empty defaults are left untouched.
_PATH_ARGS = ("vault", "folder", "out", "input", "content")


def _expand_user_paths(args: argparse.Namespace) -> None:
    """Expand a leading `~`/`~user` in every path-bearing argument, in place."""
    for attr in _PATH_ARGS:
        value = getattr(args, attr, None)
        if isinstance(value, str) and value and value != "-":
            setattr(args, attr, str(Path(value).expanduser()))


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
    regenerate.add_argument(
        "--keep-history",
        action="store_true",
        help="replay the old index's status/edit/resource/deletion events onto rebuilt notes whose "
        "ids are unchanged (history is otherwise reset by a from-scratch rebuild)",
    )

    doctor = subparsers.add_parser(
        "doctor", help="Diagnose an existing vault (note/edge/quality report); read-only."
    )
    doctor.add_argument("-o", "--vault", required=True, help="the vault directory")

    reset = subparsers.add_parser(
        "reset",
        help="Wipe a vault back to empty — deletes the Obsidian folder + grandplan's index.",
    )
    reset.add_argument("-o", "--vault", required=True, help="the vault directory")
    reset.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt (for scripts)"
    )
    reset.add_argument(
        "--keep-originals",
        action="store_true",
        help="keep your captured originals (delete only derived notes/index; `regenerate` rebuilds)",
    )

    calendar = subparsers.add_parser(
        "calendar", help="Export dated notes to an .ics calendar feed (offline; subscribe to it)."
    )
    calendar.add_argument("-o", "--vault", required=True, help="the vault directory")
    calendar.add_argument(
        "--out", default="", help="output .ics path (default: <vault>/grandplan.ics)"
    )

    report_cmd = subparsers.add_parser(
        "report",
        help="Render a stand-alone Markdown report (deliverable) from a vault.",
    )
    report_cmd.add_argument("-o", "--vault", required=True, help="the vault directory")
    report_cmd.add_argument(
        "--out", default="", help="output path (default: <vault>/report.md; use - for stdout)"
    )
    report_cmd.add_argument(
        "--title", default="", help="report title (default: 'grandplan report')"
    )

    export_cmd = subparsers.add_parser(
        "export",
        help="Export to another tool's format (Markdown Tasks or CSV) — local, offline.",
    )
    export_cmd.add_argument("-o", "--vault", required=True, help="the vault directory")
    export_cmd.add_argument(
        "--format",
        choices=("tasks", "csv", "todoist"),
        default="tasks",
        help="export format (default: tasks)",
    )
    export_cmd.add_argument(
        "--out", default="", help="output path (default: <vault>/tasks.md|export.csv; - for stdout)"
    )

    mcp_cmd = subparsers.add_parser(
        "mcp",
        help="Serve the vault to AI agents over MCP/stdio (read-only by default; needs 'mcp' extra).",
    )
    mcp_cmd.add_argument("-o", "--vault", required=True, help="the vault directory")
    mcp_cmd.add_argument(
        "--embeddings", action="store_true", help="use sentence-transformer embeddings for search"
    )
    mcp_cmd.add_argument(
        "--write",
        action="store_true",
        help="expose append-only write tools (set_status/record_edit/add_resource/place/"
        "propose_note); off by default so agents are read-only until asked",
    )
    mcp_cmd.add_argument(
        "--directives",
        action="store_true",
        help="expose directive intake tools (list_directives/complete_directive)",
    )

    directive_cmd = subparsers.add_parser(
        "directive",
        help="Queue / list agent intake directives (content + instruction) — append-only, offline.",
    )
    directive_sub = directive_cmd.add_subparsers(dest="directive_command", required=True)
    add_directive = directive_sub.add_parser("add", help="Queue a directive for the agent.")
    add_directive.add_argument("-o", "--vault", required=True, help="the vault directory")
    add_directive.add_argument(
        "--content", default="", help="content file (or - for stdin; default: stdin)"
    )
    add_directive.add_argument(
        "--playbook", default="", help="preset instruction name (e.g. profile-and-connect)"
    )
    add_directive.add_argument(
        "--prompt", default="", help="ad-hoc instruction (overrides playbook)"
    )
    list_directives = directive_sub.add_parser("list", help="List pending directives.")
    list_directives.add_argument("-o", "--vault", required=True, help="the vault directory")

    serve_cmd = subparsers.add_parser(
        "serve",
        help="HTTP directive intake — POST /directive to enqueue (binds 127.0.0.1 by default).",
    )
    serve_cmd.add_argument("-o", "--vault", required=True, help="the vault directory")
    serve_cmd.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind host (default 127.0.0.1; needs --token if routable)",
    )
    serve_cmd.add_argument("--port", type=int, default=8765, help="bind port (default 8765)")
    serve_cmd.add_argument(
        "--token", default="", help="shared secret required in 'Authorization: Bearer <token>'"
    )

    up_cmd = subparsers.add_parser(
        "up",
        help="Launch all capture surfaces at once (HTTP intake + folder-watch), agent-ready.",
    )
    up_cmd.add_argument("-o", "--vault", required=True, help="the vault directory")
    up_cmd.add_argument(
        "--init",
        action="store_true",
        help="scaffold a fresh vault (graph-coloured config + a workspace that opens on the graph)",
    )
    up_cmd.add_argument(
        "--open", action="store_true", help="open the vault's graph view in Obsidian"
    )
    up_cmd.add_argument(
        "--folder", default="", help="folder to watch (default: <vault>/_inbox, created if missing)"
    )
    up_cmd.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP bind host (default 127.0.0.1; routable needs --token)",
    )
    up_cmd.add_argument("--port", type=int, default=8765, help="HTTP bind port (default 8765)")
    up_cmd.add_argument("--token", default="", help="shared secret for the HTTP intake (Bearer)")
    up_cmd.add_argument(
        "--playbook", default="capture-and-file", help="default playbook for captured content"
    )
    up_cmd.add_argument("--prompt", default="", help="ad-hoc instruction (overrides --playbook)")
    up_cmd.add_argument(
        "--interval", type=float, default=5.0, help="folder-watch poll interval seconds (default 5)"
    )
    up_cmd.add_argument(
        "--hotkey",
        action="store_true",
        help="enable global hotkey capture: select text anywhere → press the hotkey → organized into "
        'the vault (needs the `windows` extra: pip install -e ".[windows]")',
    )
    up_cmd.add_argument(
        "--hotkey-combo",
        default="<ctrl>+<alt>+g",
        help="the global hotkey (pynput format; default <ctrl>+<alt>+g)",
    )
    up_cmd.add_argument(
        "--no-llm",
        action="store_true",
        help="hotkey captures use the offline keyword baseline (default: AI-enhance via the local "
        "model, falling back to offline when Ollama is unreachable)",
    )
    up_cmd.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model for hotkey captures")
    up_cmd.add_argument(
        "--dry-run", action="store_true", help="set up + print the banner, but don't serve"
    )

    watch_cmd = subparsers.add_parser(
        "watch",
        help="Watch a folder and enqueue a directive per new text/markdown file (offline capture).",
    )
    watch_cmd.add_argument("-o", "--vault", required=True, help="the vault directory")
    watch_cmd.add_argument("--folder", required=True, help="folder to watch for new files")
    watch_cmd.add_argument(
        "--playbook",
        default="capture-and-file",
        help="playbook for captured files (default: capture-and-file)",
    )
    watch_cmd.add_argument("--prompt", default="", help="ad-hoc instruction (overrides --playbook)")
    watch_cmd.add_argument(
        "--interval", type=float, default=5.0, help="poll interval in seconds (default 5)"
    )
    watch_cmd.add_argument("--once", action="store_true", help="scan once and exit (don't loop)")

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
    _expand_user_paths(args)
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
    if args.command == "reset":
        return _run_reset(args)
    if args.command == "calendar":
        return _run_calendar(args)
    if args.command == "report":
        return _run_report(args)
    if args.command == "export":
        return _run_export(args)
    if args.command == "directive":
        return _run_directive(args)
    if args.command == "up":
        return _run_up(args)
    if args.command == "watch":
        return _run_watch(args)
    if args.command == "serve":
        return _run_serve(args)
    if args.command == "mcp":
        return _run_mcp(args)
    return _run_organize(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
