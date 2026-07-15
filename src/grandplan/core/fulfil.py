"""Fulfil pending directives — the thing that drains the queue (SPEC-ACT §A3, ROADMAP theme J).

`POST /directive` (the phone), `grandplan directive add`, and folder-watch all append to
`directives.jsonl`. Nothing drained it: `pending()` grew forever until an external MCP agent pulled
it. This module is the in-house drain.

**No free-form tool-calling loop.** The local model does what small models are good at — extraction
and summarization — and *Python does the control flow*. A 7 B model's multi-step tool discipline is
unproven, and it isn't needed: the playbooks decompose into exactly the steps the organize pipeline
already performs. So fulfilling a directive is the structural pipeline over its content:

    capture verbatim original → organize → assess (dedup) → place → commit → record placement
      → materialize entities

**Curation stays user-directed (SPEC-ACT §5).** The runner's entire input is `store.pending()`. It
never enumerates, scans, or samples vault notes looking for work — `run_pending` is not even given a
repository, so it *cannot* reach the vault. Every directive it fulfils is content the user explicitly
sent with an instruction the user chose; fulfilling one executes a request already made, which is the
opposite of unprompted curation.

**It only marks done what it actually fulfilled.** Playbooks whose instructions need generation the
pipeline has no step for (`extract-actions`, ad-hoc prompts) are left pending for an MCP agent —
silently consuming a request you cannot satisfy is worse than leaving it queued.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from grandplan.core.directive import Directive, DirectiveStore
from grandplan.core.entities import EntityExtractor, materialize_entities
from grandplan.core.models import NoteStatus, Original, Source
from grandplan.core.pipeline import assess, commit
from grandplan.core.placement import Placer, record_placement
from grandplan.core.ports import Embedder, NoteRepository, Organizer, VaultWriter
from grandplan.core.reconcile import Reconciler
from grandplan.core.store import OriginalStore

logger = logging.getLogger(__name__)

# Playbooks the structural pipeline honestly satisfies (SPEC-ACT §A3). Adding a name here is a claim
# that running organize+place+entities over the content fulfils that playbook's instruction:
#
# - `capture-and-file` — "summarize into a note, tag it, place it under the right goal" IS organize
#   + placer, exactly.
# - `profile-and-connect` — note + entity extraction + placement is its structural core (and the
#   people graph the whole thing is for). Its closing "propose a next-step task" step is generative;
#   `FulfilResult.residual` reports it as not done rather than pretending otherwise.
#
# Deliberately excluded: `extract-actions` (a task note per action item needs generation) and ad-hoc
# `--prompt` directives (arbitrary instructions only an agent can interpret).
AUTO_FULFILLABLE = frozenset({"capture-and-file", "profile-and-connect"})

# What the pipeline cannot do for an allowlisted playbook — surfaced, never silently skipped.
_RESIDUAL: dict[str, str] = {
    "profile-and-connect": (
        "the closing “propose a next-step task” step is generative and was not run — "
        "an MCP agent (`grandplan mcp --directives --write`) can add it"
    ),
}


@dataclass(frozen=True)
class FulfilResult:
    """What fulfilling one directive actually did — including what it didn't."""

    directive_id: str
    note_id: str | None  # None when skipped as a duplicate
    entity_ids: tuple[str, ...] = ()
    skipped_duplicate: bool = False
    residual: str = ""  # the part of the playbook the pipeline could not do ("" = fully fulfilled)


def fulfil_directive(
    directive: Directive,
    *,
    repo: NoteRepository,
    originals: OriginalStore,
    embedder: Embedder,
    organizer: Organizer,
    reconciler: Reconciler,
    placer: Placer,
    entity_extractor: EntityExtractor,
    vault: VaultWriter,
    source: Source,
) -> FulfilResult:
    """Run the structural pipeline over one directive's content. Raises on pipeline failure.

    The original is stamped with the **directive's own** `created`, never a fresh clock: a note is
    dated when the user sent it, not when the queue happened to be drained (the same no-hidden-clock
    rule the capture path follows). Raising is deliberate — `run_pending` turns a failure into
    "left pending", so a retryable fault must not be swallowed here.
    """
    original = Original.capture(directive.content, source, directive.created)
    originals.add(original)  # verbatim first: the text survives whatever the organizer makes of it
    proposed = organizer.organize(original)
    assessment = assess(proposed, embedder=embedder, repo=repo, reconciler=reconciler)
    if assessment.proposal.is_probable_duplicate:
        # Fulfilled — the answer is just "you already have this". The directive IS done; re-running
        # it would only re-derive the same duplicate.
        return FulfilResult(directive_id=directive.id, note_id=None, skipped_duplicate=True)
    placement = placer.place(proposed, assessment.embedding, repo)  # before commit (no self-link)
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
    entity_ids = materialize_entities(
        repo, originals, embedder, result.note.id, entity_extractor.extract(directive.content)
    )
    return FulfilResult(
        directive_id=directive.id,
        note_id=result.note.id,
        entity_ids=entity_ids,
        residual=_RESIDUAL.get(directive.playbook, ""),
    )


def run_pending(
    store: DirectiveStore,
    *,
    fulfil: Callable[[Directive], FulfilResult],
    max_directives: int | None = None,
) -> tuple[FulfilResult, ...]:
    """Drain the pending queue through `fulfil`, marking done only what was fulfilled.

    Takes no repository by design: the queue is the runner's *entire* input, so it cannot scan the
    vault for work even by accident (SPEC-ACT §5).

    A directive whose fulfilment raises is left pending and logged — retryable, never silently
    dropped — and one bad directive never stops the rest of the pass.
    """
    done: list[FulfilResult] = []
    for directive in store.pending():
        if max_directives is not None and len(done) >= max_directives:
            break
        if directive.playbook not in AUTO_FULFILLABLE:
            logger.info(
                "directive %s (%s) left pending: needs an agent — see `grandplan mcp --directives`",
                directive.id,
                directive.playbook or "ad-hoc",
            )
            continue
        try:
            result = fulfil(directive)
        except Exception:  # noqa: BLE001 - one bad directive must not stop the pass
            logger.exception("directive %s failed; left pending for a retry", directive.id)
            continue
        store.mark_done(directive.id)
        done.append(result)
    return tuple(done)
