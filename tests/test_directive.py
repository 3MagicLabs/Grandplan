"""Tests for the directive intake spine — model, playbooks, stores, and MCP tool dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from grandplan.core.directive import (
    DIRECTIVE_TOOLS,
    PLAYBOOKS,
    Directive,
    InMemoryDirectiveStore,
    JsonlDirectiveStore,
    dispatch_directive,
    resolve_instruction,
)


def test_directive_id_is_content_addressed() -> None:
    a = Directive.create("post text", "do the thing", "2026-06-20", playbook="capture-and-file")
    b = Directive.create("post text", "do the thing", "2026-06-20", playbook="capture-and-file")
    assert a.id == b.id and not a.done


def test_resolve_instruction_prefers_prompt() -> None:
    instruction, playbook = resolve_instruction(prompt="just summarize")
    assert instruction == "just summarize" and playbook == ""


def test_resolve_instruction_uses_playbook_prompt() -> None:
    instruction, playbook = resolve_instruction(playbook="profile-and-connect")
    assert playbook == "profile-and-connect"
    assert instruction == PLAYBOOKS["profile-and-connect"].prompt


def test_resolve_instruction_unknown_playbook_raises() -> None:
    with pytest.raises(ValueError, match="unknown playbook"):
        resolve_instruction(playbook="nope")


def test_resolve_instruction_needs_one_of_them() -> None:
    with pytest.raises(ValueError, match="prompt or a --playbook"):
        resolve_instruction()


def test_in_memory_store_add_pending_and_done() -> None:
    store = InMemoryDirectiveStore()
    d = Directive.create("c", "i", "2026", playbook="capture-and-file")
    store.add(d)
    assert store.get(d.id) is d and store.get("missing") is None
    assert [x.id for x in store.pending()] == [d.id]
    assert store.mark_done(d.id) is True
    assert store.pending() == ()
    assert store.mark_done(d.id) is False  # idempotent


def test_in_memory_store_is_append_only_idempotent() -> None:
    store = InMemoryDirectiveStore()
    d = Directive.create("c", "i", "2026")
    store.add(d)
    store.add(d)
    assert len(store.all()) == 1


def test_jsonl_store_persists_and_derives_done(tmp_path: Path) -> None:
    path = tmp_path / "directives.jsonl"
    store = JsonlDirectiveStore(path)
    d = Directive.create(
        "scroll insta post", "profile them", "2026", playbook="profile-and-connect"
    )
    store.add(d)
    store.mark_done(d.id)
    # a fresh store replays the log: the directive exists and is derived done
    reloaded = JsonlDirectiveStore(path)
    assert reloaded.get(d.id) is not None
    assert reloaded.get(d.id).done is True  # type: ignore[union-attr]
    assert reloaded.pending() == ()


def test_jsonl_store_add_is_idempotent_and_all_and_missing_get(tmp_path: Path) -> None:
    store = JsonlDirectiveStore(tmp_path / "d.jsonl")
    d = Directive.create("c", "i", "2026")
    store.add(d)
    store.add(d)  # idempotent — no second record
    assert len(store.all()) == 1
    assert store.get("missing") is None
    assert store.mark_done("missing") is False  # unknown → no-op


def test_directive_tools_registry() -> None:
    assert {t.name for t in DIRECTIVE_TOOLS} == {"list_directives", "complete_directive"}


def test_dispatch_directive_list_and_complete() -> None:
    store = InMemoryDirectiveStore()
    d = Directive.create("c", "i", "2026", playbook="extract-actions")
    store.add(d)
    listed = dispatch_directive(store, "list_directives", {})
    assert isinstance(listed, list) and listed[0]["id"] == d.id
    result = dispatch_directive(store, "complete_directive", {"directive_id": d.id})
    assert isinstance(result, dict) and result["applied"] is True
    assert dispatch_directive(store, "list_directives", {}) == []


def test_dispatch_directive_unknown_tool_raises() -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        dispatch_directive(InMemoryDirectiveStore(), "nuke", {})


def test_jsonl_store_is_thread_safe_under_concurrent_adds(tmp_path: Path) -> None:
    # Concurrent writers (HTTP intake threads + `up`'s watch thread) must not corrupt the log.
    import threading

    store = JsonlDirectiveStore(tmp_path / "d.jsonl")
    barrier = threading.Barrier(8)

    def add(i: int) -> None:
        barrier.wait()  # maximize overlap
        store.add(Directive.create(f"content {i}", "do it", "2026", playbook="capture-and-file"))

    threads = [threading.Thread(target=add, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(store.all()) == 8
    # the persisted log reloads cleanly into the same 8 directives (no torn/interleaved lines)
    assert len(JsonlDirectiveStore(tmp_path / "d.jsonl").all()) == 8
