"""Tests for the VaultWrite append-only write facade + the MCP write tool registry/dispatch.

Every write is an event reusing the PR-A…PR-G repo operations (no stored note/original mutated),
validated and outcome-reported (`applied=False` on an idempotent no-op). Offline + pure, so it is
gated without the `mcp` dep (mirrors test_query.py).
"""

from __future__ import annotations

import pytest

from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import (
    Edge,
    EdgeKind,
    Horizon,
    Note,
    NoteStatus,
    NoteType,
    Original,
    Source,
)
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore
from grandplan.core.write import WRITE_TOOLS, VaultWrite, dispatch_write


def _write() -> VaultWrite:
    repo, originals, emb = InMemoryNoteRepository(), InMemoryOriginalStore(), HashingEmbedder()
    originals.add(
        Original(id="o1", text="build a second brain", source=Source(app="t"), created="2026")
    )
    goal = Note(
        id="g",
        original_id="o1",
        title="build a second brain",
        body="the vision",
        type=NoteType.GOAL,
        horizon=Horizon.GOAL,
    )
    repo.add_note(goal, emb.embed(goal.title))
    originals.add(
        Original(id="o2", text="finish the capture hotkey", source=Source(app="t"), created="2026")
    )
    task = Note(
        id="t", original_id="o2", title="finish the capture hotkey", body="do", type=NoteType.TASK
    )
    repo.add_note(task, emb.embed(task.title))
    return VaultWrite(repo=repo, originals=originals, embedder=emb)


# --- set_status -----------------------------------------------------------------------------------


def test_set_status_applies_and_records_event() -> None:
    w = _write()
    result = w.set_status("t", "active")
    assert result == {"ok": True, "applied": True, "note_id": "t", "status": "active"}
    assert w.repo.status_of("t") is NoteStatus.ACTIVE


def test_set_status_idempotent_second_call_is_no_op() -> None:
    w = _write()
    w.set_status("t", "active")
    before = len(w.repo.events())
    result = w.set_status("t", "active")
    assert result["applied"] is False
    assert len(w.repo.events()) == before  # no duplicate event


def test_set_status_unknown_note_raises() -> None:
    with pytest.raises(ValueError, match="unknown note"):
        _write().set_status("nope", "active")


def test_set_status_invalid_status_raises() -> None:
    with pytest.raises(ValueError, match="status"):
        _write().set_status("t", "frobnicated")


# --- record_edit ----------------------------------------------------------------------------------


def test_record_edit_applies() -> None:
    w = _write()
    result = w.record_edit("t", title="finish the global hotkey", due="2026-07-01")
    assert result["applied"] is True
    current = w.repo.current_note("t")
    assert current is not None
    assert current.title == "finish the global hotkey"
    assert current.due == "2026-07-01"
    assert current.id == "t"  # identity stable


def test_record_edit_tags_accepts_list() -> None:
    w = _write()
    w.record_edit("t", tags=["capture", "mvp"])
    current = w.repo.current_note("t")
    assert current is not None and current.tags == ("capture", "mvp")


def test_record_edit_no_fields_raises() -> None:
    with pytest.raises(ValueError, match="no fields"):
        _write().record_edit("t")


def test_record_edit_unknown_note_raises() -> None:
    with pytest.raises(ValueError, match="unknown note"):
        _write().record_edit("nope", title="x")


def test_record_edit_noop_when_unchanged() -> None:
    w = _write()
    result = w.record_edit("t", title="finish the capture hotkey")  # same as current
    assert result["applied"] is False


# --- add_resource ---------------------------------------------------------------------------------


def test_add_resource_applies() -> None:
    w = _write()
    result = w.add_resource("t", "link", "https://example.com", label="docs")
    assert result["applied"] is True
    refs = [(r.kind.value, r.ref) for r in w.repo.resources_of("t")]
    assert ("link", "https://example.com") in refs


def test_add_resource_idempotent() -> None:
    w = _write()
    w.add_resource("t", "link", "https://example.com")
    result = w.add_resource("t", "link", "https://example.com")
    assert result["applied"] is False


def test_add_resource_invalid_kind_raises() -> None:
    with pytest.raises(ValueError, match="kind"):
        _write().add_resource("t", "bogus", "x")


def test_add_resource_empty_ref_raises() -> None:
    with pytest.raises(ValueError, match="ref"):
        _write().add_resource("t", "link", "")


def test_add_resource_unknown_note_raises() -> None:
    with pytest.raises(ValueError, match="unknown note"):
        _write().add_resource("nope", "link", "x")


# --- place (add_edge) -----------------------------------------------------------------------------


def test_place_creates_structural_edge() -> None:
    w = _write()
    result = w.place("t", "g", "part_of")
    assert result["applied"] is True
    assert Edge("t", "g", EdgeKind.PART_OF) in w.repo.edges()


def test_place_idempotent() -> None:
    w = _write()
    w.place("t", "g", "part_of")
    result = w.place("t", "g", "part_of")
    assert result["applied"] is False


def test_place_self_loop_raises() -> None:
    with pytest.raises(ValueError, match="self"):
        _write().place("t", "t", "part_of")


def test_place_unknown_endpoint_raises() -> None:
    with pytest.raises(ValueError, match="unknown note"):
        _write().place("t", "nope", "part_of")


def test_place_invalid_kind_raises() -> None:
    with pytest.raises(ValueError, match="kind"):
        _write().place("t", "g", "bogus")


# --- propose_note ---------------------------------------------------------------------------------


def test_propose_note_creates_a_note() -> None:
    w = _write()
    result = w.propose_note(
        text="research local STT models for voice capture",
        title="research local STT models",
        type="task",
        created="2026-06-20",
        tags=["voice"],
    )
    assert result["applied"] is True
    note_id = result["note_id"]
    created = w.repo.current_note(note_id)
    assert created is not None
    assert created.title == "research local STT models"
    assert created.type is NoteType.TASK
    # the verbatim original is preserved + retrievable
    original = w.originals.get(created.original_id)
    assert original is not None and original.text == "research local STT models for voice capture"


def test_propose_note_idempotent_on_identical_input() -> None:
    w = _write()
    args = dict(text="same capture", title="same", type="idea", created="2026-06-20")
    first = w.propose_note(**args)
    second = w.propose_note(**args)
    assert first["note_id"] == second["note_id"]
    assert second["applied"] is False


def test_propose_note_empty_text_raises() -> None:
    with pytest.raises(ValueError, match="text"):
        _write().propose_note(text="", title="x", type="idea", created="2026")


def test_propose_note_empty_title_raises() -> None:
    with pytest.raises(ValueError, match="title"):
        _write().propose_note(text="x", title="", type="idea", created="2026")


def test_propose_note_empty_created_raises() -> None:
    with pytest.raises(ValueError, match="created"):
        _write().propose_note(text="x", title="x", type="idea", created="")


def test_set_status_empty_note_id_raises() -> None:
    with pytest.raises(ValueError, match="note_id"):
        _write().set_status("", "active")


def test_propose_note_invalid_type_raises() -> None:
    with pytest.raises(ValueError, match="type"):
        _write().propose_note(text="x", title="x", type="bogus", created="2026")


# --- extract_entities -----------------------------------------------------------------------------


def test_extract_entities_creates_nodes_and_edges() -> None:
    w = _write()
    w.record_edit("t", body="pair with Sarah Chen on the hotkey")
    result = w.extract_entities("t")
    assert result["applied"] is True
    assert "Sarah Chen" in result["entities"]
    assert len(result["entity_ids"]) == 1
    entity = w.repo.get_note(result["entity_ids"][0])
    assert entity is not None and entity.type is NoteType.ENTITY


def test_extract_entities_idempotent() -> None:
    w = _write()
    w.record_edit("t", body="pair with Sarah Chen")
    w.extract_entities("t")
    result = w.extract_entities("t")
    assert result["applied"] is False


def test_extract_entities_unknown_note_raises() -> None:
    with pytest.raises(ValueError, match="unknown note"):
        _write().extract_entities("nope")


def test_dispatch_write_routes_extract_entities() -> None:
    w = _write()
    w.record_edit("t", body="sync with John Doe")
    result = dispatch_write(w, "extract_entities", {"note_id": "t"})
    assert isinstance(result, dict) and "John Doe" in result["entities"]


# --- never mutates stored state (append-only invariant) -------------------------------------------


def test_writes_never_mutate_the_stored_original() -> None:
    w = _write()
    before = w.originals.get("o2")
    w.set_status("t", "done")
    w.record_edit("t", title="renamed")
    after = w.originals.get("o2")
    assert before == after  # the verbatim original is untouched


# --- WRITE_TOOLS registry + dispatch_write --------------------------------------------------------


def test_write_tools_cover_every_write_op() -> None:
    names = {tool.name for tool in WRITE_TOOLS}
    assert names == {
        "set_status",
        "record_edit",
        "add_resource",
        "place",
        "propose_note",
        "extract_entities",
    }


def test_write_tool_schemas_are_valid_json_schema() -> None:
    for tool in WRITE_TOOLS:
        assert tool.input_schema["type"] == "object"
        assert "properties" in tool.input_schema
        assert "required" in tool.input_schema


def test_dispatch_write_routes_set_status() -> None:
    w = _write()
    result = dispatch_write(w, "set_status", {"note_id": "t", "status": "active"})
    assert isinstance(result, dict) and result["applied"] is True


def test_dispatch_write_routes_record_edit() -> None:
    w = _write()
    result = dispatch_write(w, "record_edit", {"note_id": "t", "title": "new title"})
    assert isinstance(result, dict) and result["applied"] is True


def test_dispatch_write_record_edit_coerces_tags_list() -> None:
    w = _write()
    dispatch_write(w, "record_edit", {"note_id": "t", "tags": ["a", "b", 3]})
    current = w.repo.current_note("t")
    assert current is not None and current.tags == ("a", "b")  # non-strings dropped


def test_dispatch_write_routes_add_resource() -> None:
    w = _write()
    result = dispatch_write(
        w, "add_resource", {"note_id": "t", "kind": "link", "ref": "https://x.io"}
    )
    assert isinstance(result, dict) and result["applied"] is True


def test_dispatch_write_routes_place() -> None:
    w = _write()
    result = dispatch_write(w, "place", {"source_id": "t", "target_id": "g", "kind": "depends_on"})
    assert isinstance(result, dict) and result["applied"] is True


def test_dispatch_write_routes_propose_note() -> None:
    w = _write()
    result = dispatch_write(
        w,
        "propose_note",
        {"text": "a new idea", "title": "idea", "type": "idea", "created": "2026"},
    )
    assert isinstance(result, dict) and result["applied"] is True


def test_dispatch_write_unknown_tool_raises() -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        dispatch_write(_write(), "delete_everything", {})


def test_dispatch_write_missing_required_arg_raises() -> None:
    with pytest.raises(ValueError, match="note_id"):
        dispatch_write(_write(), "set_status", {"status": "active"})
