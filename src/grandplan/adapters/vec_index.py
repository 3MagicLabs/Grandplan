"""VecIndexedRepository — sqlite-vec similarity index behind the NoteRepository port (#35).

ADR-0009's planned swap: `most_similar` was a pure-Python O(N) dot-product scan, so adding one
note costs O(N) (2-4 scans per capture) and building an N-note vault costs O(N²). This wrapper
keeps ALL storage/event semantics in the inner repository (the JSONL event log stays the single
source of truth) and answers `most_similar` from a sqlite-vec (`vec0`) table on disk instead —
a SIMD C scan that stays effectively flat at personal-KB scale.

Design points:
- **The vec db is an index, not a store.** It is rebuilt/resynced from the inner repository on
  open; deleting the .db file loses nothing. Notes/edges/events never live here.
- **Identical answers or honest fallback.** Scores are the same cosine/dot values (embeddings are
  unit vectors; score = 1 - cosine distance), re-ranked with the exact brute-force tie-break.
  Any degradation — sqlite-vec missing, extension loading unsupported, mixed embedding dims from
  an embedder switch — falls back to the inner brute force: slower, never wrong.
- **Optional dependency** (`pip install grandplan[index]`): `maybe_indexed` wraps when sqlite-vec
  is importable and working, else returns the inner repository unchanged.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from grandplan.core.models import Edge, Note, NoteEdit, NoteEvent, NoteStatus
from grandplan.core.ports import NoteRepository
from grandplan.core.resources import Resource

logger = logging.getLogger(__name__)


def maybe_indexed(inner: NoteRepository, db_path: Path) -> NoteRepository:
    """Wrap `inner` with the sqlite-vec index when available; otherwise return it unchanged.

    Import, extension loading, and schema setup can each fail on exotic Python builds — every
    failure degrades to the brute-force baseline with a warning, never an error (QAS: the
    pipeline must work with zero optional deps).
    """
    try:
        import sqlite_vec  # noqa: F401 - availability probe

        return VecIndexedRepository(inner, db_path)
    except Exception as exc:  # noqa: BLE001 - ImportError, missing loadable-extension support, ...
        logger.warning("similarity index unavailable (using brute force): %s", exc)
        return inner


class VecIndexedRepository:
    """NoteRepository that delegates storage to `inner` and similarity to a sqlite-vec table."""

    def __init__(self, inner: NoteRepository, db_path: Path) -> None:
        import sqlite_vec

        self._inner = inner
        self._serialize = sqlite_vec.serialize_float32
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path))
        self._db.enable_load_extension(True)
        sqlite_vec.load(self._db)
        self._db.enable_load_extension(False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS map (note_id TEXT PRIMARY KEY, vec_rowid INTEGER NOT NULL)"
        )
        self._db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        row = self._db.execute("SELECT value FROM meta WHERE key = 'dim'").fetchone()
        self._dim: int | None = int(row[0]) if row else None
        # Mixed embedding dims (an embedder switch mid-vault) make ANY fixed-dim index wrong for
        # part of the vault → serve every query from the inner brute force instead.
        self._degraded = False
        self._sync()

    # -- similarity ------------------------------------------------------------------------------

    def most_similar(
        self, embedding: tuple[float, ...], *, limit: int = 5, threshold: float = 0.0
    ) -> tuple[tuple[Note, float], ...]:
        if self._degraded or self._dim is None or len(embedding) != self._dim:
            return self._inner.most_similar(embedding, limit=limit, threshold=threshold)
        rows = self._db.execute(
            "SELECT m.note_id, v.distance FROM vec_notes v JOIN map m ON m.vec_rowid = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ?",
            (self._serialize(list(embedding)), limit),
        ).fetchall()
        scored: list[tuple[Note, float]] = []
        for note_id, distance in rows:
            note = self._inner.get_note(str(note_id))
            if note is None:
                continue  # tombstoned/unknown — belt over the eager delete's suspenders
            score = 1.0 - float(distance)  # unit vectors: cosine distance ↔ dot score
            if score >= threshold:
                scored.append((note, score))
        scored.sort(key=lambda item: (-item[1], item[0].id))  # brute force's exact tie-break
        return tuple(scored[:limit])

    # -- writes that touch the index ---------------------------------------------------------------

    def add_note(self, note: Note, embedding: tuple[float, ...]) -> None:
        already = self._inner.get_note(note.id) is not None
        self._inner.add_note(note, embedding)
        if not already:
            self._index(note.id, embedding)

    def delete_note(self, note_id: str, *, at: str | None = None) -> None:
        self._inner.delete_note(note_id, at=at)
        row = self._db.execute("SELECT vec_rowid FROM map WHERE note_id = ?", (note_id,)).fetchone()
        if row is not None:
            self._db.execute("DELETE FROM vec_notes WHERE rowid = ?", (row[0],))
            self._db.execute("DELETE FROM map WHERE note_id = ?", (note_id,))
            self._db.commit()

    # -- index maintenance -------------------------------------------------------------------------

    def _index(self, note_id: str, embedding: tuple[float, ...]) -> None:
        if self._degraded:
            return
        if self._dim is None:
            self._dim = len(embedding)
            self._db.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING "
                f"vec0(embedding float[{self._dim}] distance_metric=cosine)"
            )
            self._db.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('dim', ?)", (str(self._dim),)
            )
        if len(embedding) != self._dim:
            logger.warning(
                "embedding dim %d != index dim %d (embedder switched?); "
                "similarity falls back to brute force",
                len(embedding),
                self._dim,
            )
            self._degraded = True
            return
        row = self._db.execute("SELECT MAX(vec_rowid) FROM map").fetchone()
        rowid = int(row[0] or 0) + 1
        self._db.execute(
            "INSERT INTO vec_notes (rowid, embedding) VALUES (?, ?)",
            (rowid, self._serialize(list(embedding))),
        )
        self._db.execute(
            "INSERT OR REPLACE INTO map (note_id, vec_rowid) VALUES (?, ?)", (note_id, rowid)
        )
        self._db.commit()

    def _sync(self) -> None:
        """Reconcile the index with the inner store: add unindexed live notes, drop stale rows.

        Runs at open; makes the .db file freely deletable (a lost index is a rebuild, not a loss)
        and heals any crash between an inner write and an index write.
        """
        indexed = {str(r[0]) for r in self._db.execute("SELECT note_id FROM map").fetchall()}
        live: set[str] = set()
        for note in self._inner.notes():
            if self._inner.get_note(note.id) is None:
                continue  # tombstoned
            live.add(note.id)
            if note.id in indexed:
                continue
            embedding = self._inner.embedding_of(note.id)
            if embedding is not None:
                self._index(note.id, embedding)
        for stale in indexed - live:
            row = self._db.execute(
                "SELECT vec_rowid FROM map WHERE note_id = ?", (stale,)
            ).fetchone()
            if row is not None:
                self._db.execute("DELETE FROM vec_notes WHERE rowid = ?", (row[0],))
                self._db.execute("DELETE FROM map WHERE note_id = ?", (stale,))
        self._db.commit()

    # -- pure delegation (storage/events stay the inner repo's job) --------------------------------

    def get_note(self, note_id: str) -> Note | None:
        return self._inner.get_note(note_id)

    def embedding_of(self, note_id: str) -> tuple[float, ...] | None:
        return self._inner.embedding_of(note_id)

    def notes(self) -> tuple[Note, ...]:
        return self._inner.notes()

    def add_edge(self, edge: Edge) -> None:
        self._inner.add_edge(edge)

    def edges(self) -> tuple[Edge, ...]:
        return self._inner.edges()

    def set_status(
        self, note_id: str, status: NoteStatus, *, at: str | None = None, detail: str = ""
    ) -> None:
        self._inner.set_status(note_id, status, at=at, detail=detail)

    def status_of(self, note_id: str) -> NoteStatus | None:
        return self._inner.status_of(note_id)

    def record_edit(self, note_id: str, edit: NoteEdit, *, at: str | None = None) -> None:
        self._inner.record_edit(note_id, edit, at=at)

    def add_resource(self, note_id: str, resource: Resource, *, at: str | None = None) -> None:
        self._inner.add_resource(note_id, resource, at=at)

    def resources_of(self, note_id: str) -> tuple[Resource, ...]:
        return self._inner.resources_of(note_id)

    def current_note(self, note_id: str) -> Note | None:
        return self._inner.current_note(note_id)

    def current_notes(self) -> tuple[Note, ...]:
        return self._inner.current_notes()

    def history_of(self, note_id: str) -> tuple[NoteEvent, ...]:
        return self._inner.history_of(note_id)

    def events(self) -> tuple[NoteEvent, ...]:
        return self._inner.events()
