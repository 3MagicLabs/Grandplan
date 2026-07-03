"""VecIndexedRepository (#35, ADR-0009): sqlite-vec similarity index behind the NoteRepository port.

Contract: a wrapped repository behaves IDENTICALLY to the brute-force baseline — same ranking,
same threshold/limit semantics, same tombstone exclusion — it just answers `most_similar` from a
sqlite-vec table instead of a Python O(N) scan. Storage/event semantics stay with the inner repo.
Degradations (sqlite-vec missing, mixed embedding dims) fall back to the inner brute force, never
wrong answers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sqlite_vec")

from grandplan.adapters.vec_index import VecIndexedRepository, maybe_indexed  # noqa: E402
from grandplan.core.embed import HashingEmbedder  # noqa: E402
from grandplan.core.models import Note, NoteStatus, NoteType  # noqa: E402
from grandplan.core.note_store import JsonlNoteRepository  # noqa: E402
from grandplan.core.repository import InMemoryNoteRepository  # noqa: E402

_TEXTS = [
    "postgres backend decision for the server",
    "postgres migration plan and rollback",
    "buy milk eggs coffee groceries",
    "wireguard tunnel setup for the phone",
    "phone shortcut sends notes over the tunnel",
    "fine tune a local model for organizing notes",
    "benchmark local models tokens per second",
    "obsidian graph view colors by note type",
]


def _note(i: int, text: str) -> Note:
    return Note(id=f"n{i}", original_id=f"o{i}", title=text[:30], body=text, type=NoteType.IDEA)


def _fill(repo: object) -> HashingEmbedder:
    embedder = HashingEmbedder()
    for i, text in enumerate(_TEXTS):
        repo.add_note(_note(i, text), embedder.embed(text))  # type: ignore[attr-defined]
    return embedder


def test_most_similar_matches_brute_force_ranking(tmp_path: Path) -> None:
    plain = InMemoryNoteRepository()
    indexed = VecIndexedRepository(InMemoryNoteRepository(), tmp_path / "vec.db")
    embedder = _fill(plain)
    _fill(indexed)
    query = embedder.embed("postgres server backend")
    expected = plain.most_similar(query, limit=4, threshold=0.05)
    got = indexed.most_similar(query, limit=4, threshold=0.05)
    assert [n.id for n, _ in got] == [n.id for n, _ in expected]
    for (_, s_got), (_, s_exp) in zip(got, expected, strict=True):
        assert s_got == pytest.approx(s_exp, abs=1e-5)  # float32 storage rounding only


def test_deleted_notes_are_never_returned(tmp_path: Path) -> None:
    indexed = VecIndexedRepository(InMemoryNoteRepository(), tmp_path / "vec.db")
    embedder = _fill(indexed)
    query = embedder.embed("postgres server backend")
    top = indexed.most_similar(query, limit=1)[0][0]
    indexed.delete_note(top.id)
    remaining = [n.id for n, _ in indexed.most_similar(query, limit=8)]
    assert top.id not in remaining and remaining  # gone from search, others still found
    assert indexed.get_note(top.id) is None  # tombstone visible through the wrapper too


def test_persists_and_resyncs_from_inner_on_reopen(tmp_path: Path) -> None:
    # The vec db is a rebuildable INDEX, not a store: reopening resyncs against the JSONL truth,
    # and deleting the db file entirely just triggers a rebuild — never data loss.
    store = tmp_path / "index.jsonl"
    db = tmp_path / "vec.db"
    embedder = _fill(VecIndexedRepository(JsonlNoteRepository(store), db))
    query = embedder.embed("postgres server backend")

    reopened = VecIndexedRepository(JsonlNoteRepository(store), db)
    assert [n.id for n, _ in reopened.most_similar(query, limit=2)] == ["n0", "n1"]

    db.unlink()  # index lost → rebuilt from the inner store on next open
    rebuilt = VecIndexedRepository(JsonlNoteRepository(store), db)
    assert [n.id for n, _ in rebuilt.most_similar(query, limit=2)] == ["n0", "n1"]


def test_mixed_embedding_dims_degrade_to_brute_force_not_wrong_answers(tmp_path: Path) -> None:
    plain = InMemoryNoteRepository()
    indexed = VecIndexedRepository(InMemoryNoteRepository(), tmp_path / "vec.db")
    embedder = _fill(plain)
    _fill(indexed)
    odd = _note(99, "a differently embedded note")
    plain.add_note(odd, (1.0, 0.0))  # 2-dim vector in a 256-dim vault (embedder switched)
    indexed.add_note(odd, (1.0, 0.0))
    query = embedder.embed("postgres server backend")
    expected = plain.most_similar(query, limit=4)
    got = indexed.most_similar(query, limit=4)
    assert [n.id for n, _ in got] == [n.id for n, _ in expected]  # identical, via fallback


def test_events_and_edges_delegate_to_inner(tmp_path: Path) -> None:
    indexed = VecIndexedRepository(InMemoryNoteRepository(), tmp_path / "vec.db")
    _fill(indexed)
    indexed.set_status("n0", NoteStatus.DONE)
    assert indexed.status_of("n0") is NoteStatus.DONE
    assert indexed.current_note("n0") is not None
    assert len(indexed.notes()) == len(_TEXTS)
    assert indexed.history_of("n0")  # event log reachable through the wrapper


def test_maybe_indexed_returns_inner_when_sqlite_vec_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    real_import = builtins.__import__

    def _blocked(name: str, *args: object, **kwargs: object) -> object:
        if name == "sqlite_vec":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _blocked)
    inner = InMemoryNoteRepository()
    assert maybe_indexed(inner, tmp_path / "vec.db") is inner  # graceful: baseline, not a crash


def test_maybe_indexed_wraps_when_available(tmp_path: Path) -> None:
    wrapped = maybe_indexed(InMemoryNoteRepository(), tmp_path / "vec.db")
    assert isinstance(wrapped, VecIndexedRepository)
