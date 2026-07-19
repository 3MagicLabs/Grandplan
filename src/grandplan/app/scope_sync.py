"""Resolve the Obsidian graph filter into a chat scope (SPEC-SCOPE §5) — read → select → summarize.

The seam between the CLI REPL and the GUI chat window: both call `resolve_graph_scope` to turn the
current graph Filters box into a set of note ids plus a one-line, human-legible summary (what the
filter was, how many notes it matched, and any operators that couldn't be honored). The heavy lifting
is pure — `adapters.obsidian_graph.read_graph_filter` (IO) and `core.scope` (matching) — so this file
stays a thin, testable coordinator.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from grandplan.adapters.obsidian_graph import read_graph_filter
from grandplan.core.ports import NoteRepository
from grandplan.core.scope import parse_filter, select
from grandplan.core.vault import plan_filenames


@dataclass(frozen=True)
class ScopeResult:
    """The outcome of a sync: the scoped ids (empty = whole vault) and how to describe it."""

    ids: frozenset[str]
    raw: str  # the filter string read from the graph, "" when none
    total: int  # notes in the vault
    narrowed: bool  # did the filter actually restrict the set?
    unsupported: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.ids)

    def summary(self) -> str:
        """A single status line for the REPL / the GUI chip."""
        if not self.raw:
            return "no graph filter set — chatting over the whole vault."
        if not self.narrowed:
            return f"graph filter {self.raw!r} doesn't narrow anything — chatting over the whole vault."
        if self.count == 0:
            return (
                f"graph filter {self.raw!r} matched 0 notes — nothing to scope to; "
                "widen it or clear it. Chatting over the whole vault."
            )
        line = f"scoped to {self.count} of {self.total} notes — graph filter {self.raw!r}."
        if self.unsupported:
            ignored = ", ".join(self.unsupported)
            line += f" (ignored {ignored}; scope may be broader than your graph.)"
        return line


def resolve_graph_scope(vault_dir: Path, repo: NoteRepository) -> ScopeResult:
    """Read the graph filter for `vault_dir` and select the notes it matches over `repo`.

    Returns empty `ids` (no scope) whenever the filter is absent, doesn't narrow, or matches nothing —
    every case where scoping would either be a no-op or leave the user with an empty conversation, so
    chat falls back to the whole vault and says why (`ScopeResult.summary`).
    """
    notes = repo.current_notes()
    total = len(notes)
    raw = read_graph_filter(vault_dir) or ""
    if not raw:
        return ScopeResult(ids=frozenset(), raw="", total=total, narrowed=False)
    query = parse_filter(raw)
    if not query.has_positive():
        # An all-negation/empty filter (grandplan's own default) narrows nothing → the whole vault.
        return ScopeResult(
            ids=frozenset(), raw=raw, total=total, narrowed=False, unsupported=query.unsupported
        )
    # `narrowed=True`: the filter *tried* to restrict. If it matched 0 notes the ids are empty and
    # chat falls back to the whole vault, but the summary must say "matched 0 notes", not "doesn't
    # narrow" — those are different situations the user needs told apart.
    matched = select(query, notes, plan_filenames(notes))
    return ScopeResult(
        ids=matched, raw=raw, total=total, narrowed=True, unsupported=query.unsupported
    )
