"""Tests for the MarkdownVaultWriter / render_markdown."""

from __future__ import annotations

from pathlib import Path

from grandplan.core.models import Edge, EdgeKind, Note, NoteStatus, NoteType, Original, Source
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
    assert 'status: "inbox"' in md  # defaults to the note's own status when none is passed


def test_frontmatter_renders_derived_status_override() -> None:
    # PR-A: the vault writes the *derived* current status (passed in), without mutating the note.
    note = _note()  # creation status defaults to INBOX
    md = render_markdown(note, _original(), (), status=NoteStatus.DONE)
    assert 'status: "done"' in md
    assert note.status is NoteStatus.INBOX  # note object untouched (lossless)
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


def test_render_resolves_links_to_id_alias_with_title() -> None:
    edge = Edge("abc123", "target9", EdgeKind.DEPENDS_ON)
    md = render_markdown(_note(), _original(), (edge,), targets={"target9": _target()})
    assert "## Links" in md
    # Alias-based wikilink: resolves via the target's `aliases: ["<id>"]`, displays the title,
    # and is independent of the (now clean, id-free) filename.
    assert "depends_on [[target9|Build resume]]" in md
    assert "build-resume-target9" not in md  # the id is no longer baked into the link/filename


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
    assert path.name == "project-kickoff.md"  # clean slug; id is in frontmatter, not the name
    assert "verbatim original text" in path.read_text(encoding="utf-8")


def test_same_title_different_notes_never_clobber(tmp_path: Path) -> None:
    writer = MarkdownVaultWriter(tmp_path / "vault")
    first = writer.write(_note(), _original(), ())
    other = Note(
        id="zzz999", original_id="o2", title="Project kickoff", body="other", type=NoteType.TASK
    )
    second = writer.write(other, _original(), ())
    assert first.name == "project-kickoff.md"
    assert second.name == "project-kickoff-zzz999.md"  # disambiguated, original preserved
    assert "do the thing" in first.read_text(encoding="utf-8")  # first not overwritten


def test_rewriting_same_note_overwrites_in_place(tmp_path: Path) -> None:
    writer = MarkdownVaultWriter(tmp_path / "vault")
    writer.write(_note(), _original(), ())
    again = writer.write(_note(), _original(), ())  # same id → idempotent, no suffix
    assert again.name == "project-kickoff.md"


def test_tags_are_sanitized_for_obsidian() -> None:
    note = Note(
        id="t1",
        original_id="o1",
        title="x",
        body="b",
        type=NoteType.IDEA,
        tags=("machine learning", "AI/ML", "2024", "  ", "valid-tag", "machine learning"),
    )
    frontmatter = render_markdown(note, _original(), ()).split("\n---", 1)[0]
    assert '"machine-learning"' in frontmatter  # space -> hyphen
    assert '"ai/ml"' in frontmatter  # lowercased, nested tag preserved
    assert '"valid-tag"' in frontmatter
    assert '"2024"' not in frontmatter  # purely-numeric tag dropped
    assert frontmatter.count("machine-learning") == 1  # de-duplicated


def test_planning_properties_emitted_only_when_present() -> None:
    plain = render_markdown(_note(), _original(), ()).split("\n---", 1)[0]
    assert "contexts:" not in plain and "due:" not in plain  # uncluttered when unset

    rich = Note(
        id="r1",
        original_id="o1",
        title="x",
        body="b",
        type=NoteType.TASK,
        due="2026-07-01",
        contexts=("@work",),
        collections=("launch",),
    )
    fm = render_markdown(rich, _original(), ()).split("\n---", 1)[0]
    assert 'due: "2026-07-01"' in fm
    assert "@work" in fm
    assert "launch" in fm
