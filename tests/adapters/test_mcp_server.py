"""Tests for the MCP server's pure routing helpers (`tools_for` / `route`).

The stdio shell (`run_stdio_server`) needs the optional `mcp` runtime and is `# pragma: no cover`,
but the read-vs-write routing and the read-only guard are pure and gated here without `mcp`.
"""

from __future__ import annotations

import pytest

from grandplan.adapters.mcp_server import route, tools_for
from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Note, NoteStatus, NoteType, Original, Source
from grandplan.core.query import TOOLS, VaultQuery
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore
from grandplan.core.write import WRITE_TOOLS, VaultWrite


def _vault() -> tuple[VaultQuery, VaultWrite]:
    repo, originals, emb = InMemoryNoteRepository(), InMemoryOriginalStore(), HashingEmbedder()
    originals.add(Original(id="o1", text="a task", source=Source(app="t"), created="2026"))
    note = Note(id="t", original_id="o1", title="a task", body="do", type=NoteType.TASK)
    repo.add_note(note, emb.embed(note.title))
    query = VaultQuery(repo=repo, originals=originals, embedder=emb)
    write = VaultWrite(repo=repo, originals=originals, embedder=emb)
    return query, write


def test_tools_for_read_only_excludes_write_tools() -> None:
    names = {tool.name for tool in tools_for(write_enabled=False)}
    assert names == {tool.name for tool in TOOLS}
    assert "set_status" not in names


def test_tools_for_write_enabled_includes_both() -> None:
    names = {tool.name for tool in tools_for(write_enabled=True)}
    assert {tool.name for tool in TOOLS} <= names
    assert {tool.name for tool in WRITE_TOOLS} <= names


def test_route_dispatches_a_read_tool() -> None:
    query, _ = _vault()
    result = route(query, None, "list_notes", {})
    assert isinstance(result, list) and result[0]["id"] == "t"


def test_route_dispatches_a_write_tool_when_enabled() -> None:
    query, write = _vault()
    result = route(query, write, "set_status", {"note_id": "t", "status": "active"})
    assert isinstance(result, dict) and result["applied"] is True
    assert write.repo.status_of("t") is NoteStatus.ACTIVE


def test_route_rejects_write_tool_when_read_only() -> None:
    query, _ = _vault()
    with pytest.raises(ValueError, match="unknown tool"):
        route(query, None, "set_status", {"note_id": "t", "status": "active"})


def test_route_unknown_tool_raises() -> None:
    query, write = _vault()
    with pytest.raises(ValueError, match="unknown tool"):
        route(query, write, "nuke", {})


def test_tools_for_directives_enabled_includes_directive_tools() -> None:
    from grandplan.core.directive import DIRECTIVE_TOOLS

    names = {t.name for t in tools_for(write_enabled=False, directives_enabled=True)}
    assert {t.name for t in DIRECTIVE_TOOLS} <= names


def test_route_dispatches_directive_tool_when_enabled() -> None:
    from grandplan.core.directive import Directive, InMemoryDirectiveStore

    query, _ = _vault()
    store = InMemoryDirectiveStore()
    store.add(Directive.create("post", "profile them", "2026", playbook="profile-and-connect"))
    listed = route(query, None, "list_directives", {}, store)
    assert isinstance(listed, list) and len(listed) == 1


def test_route_rejects_directive_tool_when_disabled() -> None:
    query, _ = _vault()
    with pytest.raises(ValueError, match="unknown tool"):
        route(query, None, "list_directives", {})
