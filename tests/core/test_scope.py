"""Tests for the Obsidian-graph-filter parser and note selector (SPEC-SCOPE §4).

The whole promise of scoped chat is "the notes your filter shows are the only ones chat can reach",
so these pin the grammar exactly: which notes a given filter string selects, and that unsupported
operators are surfaced (never silently changing the set) rather than dropped in secret.
"""

from __future__ import annotations

from grandplan.core.models import Note, NoteStatus, NoteType
from grandplan.core.scope import parse_filter, select


def _note(
    note_id: str,
    *,
    title: str = "",
    body: str = "",
    tags: tuple[str, ...] = (),
    type: NoteType = NoteType.IDEA,
    status: NoteStatus = NoteStatus.INBOX,
) -> Note:
    return Note(
        id=note_id,
        original_id=f"o-{note_id}",
        title=title,
        body=body,
        type=type,
        status=status,
        tags=tags,
    )


def _select(search: str, notes: tuple[Note, ...], stems: dict[str, str] | None = None) -> set[str]:
    stems = stems or {n.id: n.title.lower().replace(" ", "-") for n in notes}
    return set(select(parse_filter(search), notes, stems))


# --- keywords (AND by default) -------------------------------------------------------------------


def test_keyword_matches_title_body_and_tags_case_insensitively() -> None:
    notes = (
        _note("a", title="Career growth plan"),
        _note("b", body="notes on my CAREER path"),
        _note("c", tags=("career",)),
        _note("d", title="unrelated"),
    )
    assert _select("career", notes) == {"a", "b", "c"}


def test_multiple_keywords_are_anded() -> None:
    notes = (
        _note("a", title="career", body="education roadmap"),
        _note("b", title="career only"),
        _note("c", body="education only"),
    )
    assert _select("career education", notes) == {"a"}


def test_quoted_phrase_matches_as_one_term() -> None:
    notes = (
        _note("a", body="my career development plan"),
        _note("b", body="career and development, separately"),
    )
    # "career development" is a phrase: b has both words but not adjacent, so only a matches.
    assert _select('"career development"', notes) == {"a"}


# --- tags ----------------------------------------------------------------------------------------


def test_hash_tag_and_tag_operator_are_equivalent() -> None:
    notes = (_note("a", tags=("career",)), _note("b", tags=("other",)))
    assert _select("#career", notes) == {"a"}
    assert _select("tag:career", notes) == {"a"}
    assert _select("tag:#career", notes) == {"a"}


def test_nested_tag_matches_parent() -> None:
    notes = (_note("a", tags=("career/growth",)), _note("b", tags=("careerist",)))
    # #career matches the nested career/growth but NOT the unrelated "careerist".
    assert _select("#career", notes) == {"a"}


def test_type_and_status_pseudo_tags_match_the_note_fields() -> None:
    notes = (
        _note("a", type=NoteType.PROJECT, status=NoteStatus.DONE),
        _note("b", type=NoteType.IDEA, status=NoteStatus.DONE),
        _note("c", type=NoteType.PROJECT, status=NoteStatus.ACTIVE),
    )
    assert _select("tag:#type/project", notes) == {"a", "c"}
    assert _select("tag:#status/done", notes) == {"a", "b"}


# --- paths ---------------------------------------------------------------------------------------


def test_path_and_file_match_the_rendered_stem() -> None:
    notes = (_note("a", title="Career Plan"), _note("b", title="Grocery List"))
    stems = {"a": "Career-Plan", "b": "Grocery-List"}
    assert _select("path:career", notes, stems) == {"a"}
    assert _select("file:grocery", notes, stems) == {"b"}


# --- negation & OR -------------------------------------------------------------------------------


def test_negation_excludes_matches() -> None:
    notes = (
        _note("a", title="career", body="intro material"),
        _note("b", title="career", body="advanced material"),
    )
    assert _select("career -intro", notes) == {"b"}


def test_or_unions_the_groups() -> None:
    notes = (
        _note("a", tags=("career",)),
        _note("b", tags=("health",)),
        _note("c", tags=("cooking",)),
    )
    assert _select("#career OR #health", notes) == {"a", "b"}


# --- "no narrowing" means the whole vault --------------------------------------------------------


def test_empty_filter_selects_everything() -> None:
    notes = (_note("a"), _note("b"))
    assert _select("", notes) == {"a", "b"}
    assert not parse_filter("").has_positive()


def test_grandplans_own_default_negation_filter_selects_everything() -> None:
    # The filter write_obsidian_config installs is all-negation (hide generated MOCs). It must read
    # back as "no scope" — the whole vault — not as an empty set.
    notes = (_note("a", title="Real Note"), _note("b", title="Another"))
    default = '-path:"Plan.md" -path:"graph.json" -path:"Masterplan.md"'
    query = parse_filter(default)
    assert not query.has_positive()
    assert _select(default, notes) == {"a", "b"}


# --- unsupported operators are reported, never silently dropped -----------------------------------


def test_unsupported_operators_are_recorded() -> None:
    query = parse_filter("career line:5 [status] /regex/ (group)")
    assert "career" in {term.value for group in query.groups for term in group}
    # Every operator we can't mirror is surfaced for the caller to warn about.
    assert set(query.unsupported) == {"line:5", "[status]", "/regex/", "(group)"}


def test_unsupported_operators_fail_open_not_closed() -> None:
    # A stray unsupported token must not empty the conversation: the supported part still selects.
    notes = (_note("a", tags=("career",)), _note("b", tags=("other",)))
    assert _select("#career line:5", notes) == {"a"}
