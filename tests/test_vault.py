"""Tests for the MarkdownVaultWriter / render_markdown."""

from __future__ import annotations

from pathlib import Path

from grandplan.core.models import Edge, EdgeKind, Note, NoteType, Original, Source
from grandplan.core.vault import MarkdownVaultWriter, render_markdown


def _note() -> Note:
    return Note(
        id="abc123",
        original_id="o1",
        title="Project kickoff",
        body="do the thing",
        type=NoteType.TASK,
        tags=("project",),
    )


def _original(text: str = "verbatim original text") -> Original:
    return Original(
        id="o1",
        text=text,
        source=Source(app="Notepad", title="n.txt"),
        created="2026-06-15T00:00:00Z",
    )


def test_render_has_frontmatter_title_body_and_source() -> None:
    md = render_markdown(_note(), _original(), ())
    assert md.startswith("---\n")
    assert 'id: "abc123"' in md
    assert 'type: "task"' in md
    assert "# Project kickoff" in md
    assert "do the thing" in md
    assert "## Source (original)" in md
    assert "verbatim original text" in md


def test_render_preserves_backticks_with_expanded_fence() -> None:
    md = render_markdown(_note(), _original("inline ``` triple backticks ```"), ())
    assert "inline ``` triple backticks ```" in md
    assert "````" in md  # fence expanded beyond the inner run


def test_render_includes_links_section() -> None:
    edge = Edge("abc123", "target9", EdgeKind.DEPENDS_ON)
    md = render_markdown(_note(), _original(), (edge,))
    assert "## Links" in md
    # Without a resolved target, fall back to a bare-id link (still resolvable via alias).
    assert "depends_on [[target9]]" in md


def _target() -> Note:
    return Note(
        id="target9",
        original_id="o2",
        title="Build resume",
        body="...",
        type=NoteType.PROJECT,
    )


def test_render_resolves_links_to_filename_with_title() -> None:
    edge = Edge("abc123", "target9", EdgeKind.DEPENDS_ON)
    md = render_markdown(_note(), _original(), (edge,), targets={"target9": _target()})
    assert "## Links" in md
    # Resolvable wikilink: points at the real filename stem, displays the title.
    assert "depends_on [[build-resume-target9|Build resume]]" in md


def test_render_flattens_source_and_adds_alias() -> None:
    md = render_markdown(_note(), _original(), ())
    frontmatter = md.split("\n---", 1)[0]
    assert 'aliases: ["abc123"]' in frontmatter  # bare-id links resolve via alias
    assert 'source_app: "Notepad"' in frontmatter
    assert 'source_title: "n.txt"' in frontmatter
    assert "source: {" not in frontmatter  # no malformed nested object (the Obsidian bug)
    assert '"app"' not in frontmatter


def test_writer_creates_file_with_verbatim_original(tmp_path: Path) -> None:
    path = MarkdownVaultWriter(tmp_path / "vault").write(_note(), _original(), ())
    assert path.exists()
    assert path.suffix == ".md"
    assert path.name == "project-kickoff-abc123.md"  # slug + content id
    assert "verbatim original text" in path.read_text(encoding="utf-8")
