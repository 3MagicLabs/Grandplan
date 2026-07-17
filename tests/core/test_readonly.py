"""Tests for the read-only seal (SPEC-READONLY).

The guarantee `--read-only` makes is "this process cannot modify the vault". That is proven HERE, on
the proxies, not by inspecting a Qt window: every mutator raises, every reader delegates, and the
mutator list is pinned against the port so a newly-added write path cannot slip through unsealed.
"""

from __future__ import annotations

import pytest

from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import (
    Edge,
    EdgeKind,
    Note,
    NoteEdit,
    NoteStatus,
    NoteType,
    Original,
    Resource,
    Source,
)
from grandplan.core.ports import NoteRepository
from grandplan.core.readonly import (
    ReadOnlyRepository,
    ReadOnlyVaultWriter,
    VaultIsReadOnly,
    seal,
)
from grandplan.core.repository import InMemoryNoteRepository

_SOURCE = Source(app="test", title="t")


def _note(note_id: str = "n1", title: str = "A Note") -> Note:
    return Note(
        id=note_id, original_id=f"o-{note_id}", title=title, body="body", type=NoteType.IDEA
    )


def _populated() -> InMemoryNoteRepository:
    repo = InMemoryNoteRepository()
    embedder = HashingEmbedder()
    first, second = _note("n1", "First"), _note("n2", "Second")
    repo.add_note(first, embedder.embed(first.body))
    repo.add_note(second, embedder.embed(second.body))
    repo.add_edge(Edge(source_id="n1", target_id="n2", kind=EdgeKind.RELATES))
    return repo


# --- the seal ------------------------------------------------------------------------------------


def test_every_mutator_raises_and_nothing_reaches_the_inner_repo() -> None:
    inner = _populated()
    ro = ReadOnlyRepository(inner)
    before_notes, before_edges = inner.notes(), inner.edges()

    with pytest.raises(VaultIsReadOnly):
        ro.add_note(_note("n3"), (0.0,))
    with pytest.raises(VaultIsReadOnly):
        ro.add_edge(Edge(source_id="n1", target_id="n2", kind=EdgeKind.DEPENDS_ON))
    with pytest.raises(VaultIsReadOnly):
        ro.set_status("n1", NoteStatus.DONE)
    with pytest.raises(VaultIsReadOnly):
        ro.record_edit("n1", NoteEdit(title="Hijacked"))
    with pytest.raises(VaultIsReadOnly):
        ro.add_resource("n1", Resource(kind="url", ref="http://x", label="x"))
    with pytest.raises(VaultIsReadOnly):
        ro.delete_note("n1")

    # The point of the seal: not just that it raised, but that nothing changed underneath.
    assert inner.notes() == before_notes
    assert inner.edges() == before_edges
    assert inner.status_of("n1") != NoteStatus.DONE


def test_vault_writer_refuses_to_put_a_file_on_disk() -> None:
    original = Original.capture("text", _SOURCE, "2026-07-16T00:00:00+00:00")
    with pytest.raises(VaultIsReadOnly):
        ReadOnlyVaultWriter().write(_note(), original, ())


def test_the_error_names_the_operation_and_says_nothing_was_written() -> None:
    # SPEC-READONLY §3.2: loud, never silent — a blocked write must be legible to the user, not a
    # bare exception type they have to go read source to understand.
    with pytest.raises(VaultIsReadOnly) as caught:
        ReadOnlyRepository(_populated()).delete_note("n1")
    message = str(caught.value)
    assert "deleting a note" in message
    assert "Nothing has been written" in message
    assert "--read-only" in message


# --- reads stay whole (SPEC-READONLY §3.4) -------------------------------------------------------


def test_every_reader_delegates_unchanged() -> None:
    inner = _populated()
    ro = ReadOnlyRepository(inner)

    assert ro.get_note("n1") == inner.get_note("n1")
    assert ro.current_note("n1") == inner.current_note("n1")
    assert ro.notes() == inner.notes()
    assert ro.current_notes() == inner.current_notes()
    assert ro.edges() == inner.edges()
    assert ro.status_of("n1") == inner.status_of("n1")
    assert ro.resources_of("n1") == inner.resources_of("n1")
    assert ro.embedding_of("n1") == inner.embedding_of("n1")


def test_retrieval_works_so_chat_is_undegraded() -> None:
    # Chat is the whole reason this mode exists: if similarity search didn't pass through, read-only
    # would be a mode nobody uses.
    inner = _populated()
    ro = ReadOnlyRepository(inner)
    query = HashingEmbedder().embed("body")

    assert ro.most_similar(query, limit=5) == inner.most_similar(query, limit=5)
    assert len(ro.most_similar(query, limit=5)) > 0


# --- the seal cannot silently rot ----------------------------------------------------------------


def test_seal_returns_readonly_versions_of_both_ports() -> None:
    repo, vault = seal(_populated(), ReadOnlyVaultWriter())
    assert isinstance(repo, ReadOnlyRepository)
    assert isinstance(vault, ReadOnlyVaultWriter)


def test_an_unknown_port_method_is_not_silently_forwarded() -> None:
    # No __getattr__ by design (SPEC-READONLY §3.1): a mutator added to NoteRepository later must NOT
    # pass through to the real repo just because this proxy doesn't know about it. It fails here, in
    # the tests, instead of silently writing to a vault the user was promised was sealed.
    ro = ReadOnlyRepository(_populated())
    with pytest.raises(AttributeError):
        ro.some_future_mutator("n1")  # type: ignore[attr-defined]


def test_the_proxy_covers_every_method_on_the_port() -> None:
    # Derived from NoteRepository itself, not a hand-written list: a method added to the port must be
    # consciously classified as a read (delegate) or a write (seal). Because there is no __getattr__,
    # an unlisted method doesn't fall through to the real repo — it AttributeErrors — so the failure
    # mode is a crash rather than an unsealed write. This test turns that crash into a red test.
    # It has already earned its keep: the first version of the proxy silently omitted history_of and
    # events, and only mypy noticed.
    port_methods = {name for name in dir(NoteRepository) if not name.startswith("_")}
    ro = ReadOnlyRepository(_populated())
    missing = {name for name in port_methods if not hasattr(ro, name)}
    assert not missing, f"NoteRepository methods absent from ReadOnlyRepository: {sorted(missing)}"


def test_every_port_mutator_is_sealed() -> None:
    # The mutator/reader split is a semantic judgment, so this list is deliberately hand-written:
    # adding a write method to the port should force a human to add it HERE too.
    mutators = {
        "add_note",
        "add_edge",
        "set_status",
        "record_edit",
        "add_resource",
        "delete_note",
    }
    inner = _populated()
    ro = ReadOnlyRepository(inner)
    for name in mutators:
        assert hasattr(ro, name), f"{name} is on the port but not sealed"
        with pytest.raises(VaultIsReadOnly):
            getattr(ro, name)(*_args_for(name))


def test_set_status_accepts_the_ports_full_signature() -> None:
    # Regression: the proxy originally omitted `detail`, so a real caller passing it would have hit
    # a TypeError instead of VaultIsReadOnly — still safe, but an error that names the wrong problem.
    with pytest.raises(VaultIsReadOnly):
        ReadOnlyRepository(_populated()).set_status(
            "n1", NoteStatus.DONE, at="2026-07-16T00:00:00+00:00", detail="from a capture"
        )


def _args_for(name: str) -> tuple[object, ...]:
    return {
        "add_note": (_note("x"), (0.0,)),
        "add_edge": (Edge(source_id="n1", target_id="n2", kind=EdgeKind.RELATES),),
        "set_status": ("n1", NoteStatus.DONE),
        "record_edit": ("n1", NoteEdit(title="x")),
        "add_resource": ("n1", Resource(kind="url", ref="http://x", label="x")),
        "delete_note": ("n1",),
    }[name]
