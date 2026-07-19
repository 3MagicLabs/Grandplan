"""Parse an Obsidian graph *filter* and select the notes it matches (SPEC-SCOPE §4, pure).

Obsidian persists the graph Filters box to `.obsidian/graph.json` under `search`. This module reads
that query string back and reproduces the note set it selects, so chat can restrict retrieval to
exactly what the user filtered to in the graph. It is pure — no IO, no repo — so it is fully
unit-tested; the file read lives in `adapters.obsidian_graph` and the glue in `app.scope_sync`.

Faithfulness (SPEC-SCOPE §3): Obsidian saves only the *query*, never the visible nodes, so scope is
the query re-applied to the notes. The supported operators (keyword/AND, `#tag`/`tag:`, `type/`,
`status/`, `path:`/`file:`, `-negation`, `OR`) are honored exactly; unsupported ones (`line:`,
`section:`, `block:`, `[property]`, `/regex/`, parentheses) are *recorded* in `ScopeQuery.unsupported`
so the caller can warn — never silently dropped — and matching fails open (superset) rather than
closed, so a stray token can't empty the conversation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from grandplan.core.models import Note

_OR = "OR"  # Obsidian's alternation keyword (case-sensitive), between AND-groups
_UNSUPPORTED_PREFIXES = ("line:", "section:", "block:")
_TYPE_PREFIX = "type/"
_STATUS_PREFIX = "status/"


@dataclass(frozen=True)
class Term:
    """One filter atom: a `keyword`, `tag`, or `path` match, optionally negated."""

    kind: str  # "keyword" | "tag" | "path"
    value: str  # normalized (lowercased; tags stripped of a leading '#')
    negated: bool = False


@dataclass(frozen=True)
class ScopeQuery:
    """A parsed graph filter: OR of AND-groups, plus the operators we couldn't honor.

    A note is selected when it satisfies *any* group; a group is satisfied when every positive term
    matches and no negated term matches.
    """

    groups: tuple[tuple[Term, ...], ...] = ()
    unsupported: tuple[str, ...] = field(default_factory=tuple)

    def has_positive(self) -> bool:
        """True when at least one non-negated term exists — i.e. the filter actually narrows.

        A filter that is empty or all-negation (grandplan's own default `-path:"Plan.md" …` is the
        common case) narrows nothing, so `select` returns the whole vault: no scope.
        """
        return any(not term.negated for group in self.groups for term in group)


def _tokenize(search: str) -> list[str]:
    """Split on whitespace, keeping `"quoted phrases"` (and `'single'`) as one token.

    A leading `-` or an operator prefix stays attached to its token (`-"a b"` → `-a b`,
    `path:"Plan.md"` → `path:Plan.md`), so classification sees the whole atom.
    """
    tokens: list[str] = []
    buf: list[str] = []
    quote = ""
    for ch in search:
        if quote:
            if ch == quote:
                quote = ""
            else:
                buf.append(ch)
        elif ch in ('"', "'"):
            quote = ch
        elif ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


def _classify(raw: str, unsupported: list[str]) -> Term | None:
    """A raw token → a `Term`, or `None` (skipped) after recording an unsupported operator."""
    negated = raw.startswith("-")
    body = raw[1:] if negated else raw
    lower = body.lower()
    if not body:
        return None
    if body.startswith("/") or body.startswith("[") or "(" in body or ")" in body:
        unsupported.append(raw)  # regex, property, or parenthesized group — can't mirror exactly
        return None
    if any(lower.startswith(prefix) for prefix in _UNSUPPORTED_PREFIXES):
        unsupported.append(raw)  # line:/section:/block: operate below note granularity
        return None
    if lower.startswith("tag:"):
        return _term("tag", body[4:].lstrip("#").lower(), negated)
    if lower.startswith("path:"):
        return _term("path", body[5:].lower(), negated)
    if lower.startswith("file:"):
        return _term("path", body[5:].lower(), negated)
    if body.startswith("#"):
        return _term("tag", body.lstrip("#").lower(), negated)
    return _term("keyword", lower, negated)


def _term(kind: str, value: str, negated: bool) -> Term | None:
    """Build a term, dropping the empty ones (`#`, `tag:`, `path:` alone match nothing meaningful)."""
    return Term(kind, value, negated) if value.strip() else None


def parse_filter(search: str) -> ScopeQuery:
    """Parse an Obsidian graph `search` string into a `ScopeQuery` (pure; never raises)."""
    groups: list[list[Term]] = [[]]
    unsupported: list[str] = []
    for raw in _tokenize(search):
        if raw == _OR:
            groups.append([])
            continue
        term = _classify(raw, unsupported)
        if term is not None:
            groups[-1].append(term)
    packed = tuple(tuple(group) for group in groups if group)
    return ScopeQuery(groups=packed, unsupported=tuple(unsupported))


def _tag_matches(value: str, note: Note) -> bool:
    if value.startswith(_TYPE_PREFIX):
        return note.type.value.lower() == value[len(_TYPE_PREFIX) :]
    if value.startswith(_STATUS_PREFIX):
        return note.status.value.lower() == value[len(_STATUS_PREFIX) :]
    return any(tag.lower() == value or tag.lower().startswith(value + "/") for tag in note.tags)


def _term_matches(term: Term, note: Note, stem: str) -> bool:
    if term.kind == "path":
        return term.value in stem.lower()
    if term.kind == "tag":
        return _tag_matches(term.value, note)
    haystack = f"{note.title}\n{note.body}\n{' '.join(note.tags)}".lower()
    return term.value in haystack


def _group_matches(group: tuple[Term, ...], note: Note, stem: str) -> bool:
    for term in group:
        hit = _term_matches(term, note, stem)
        if hit == term.negated:  # positive that missed, or negated that hit → group fails
            return False
    return True


def select(query: ScopeQuery, notes: Iterable[Note], stems: Mapping[str, str]) -> frozenset[str]:
    """Ids of the notes the filter selects. No narrowing term → the whole set (SPEC-SCOPE §4)."""
    note_list = tuple(notes)
    if not query.has_positive():
        return frozenset(note.id for note in note_list)
    return frozenset(
        note.id
        for note in note_list
        if any(_group_matches(group, note, stems.get(note.id, "")) for group in query.groups)
    )
