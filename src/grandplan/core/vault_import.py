"""Merge one vault's notes into another (cross-vault import).

grandplan keeps each vault's notes as an **append-only** event log (`index.jsonl`) plus the verbatim
captures (`inbox.jsonl`), in an external per-vault index dir. Importing = appending the source vault's
records for notes the destination doesn't already have — never rewriting the destination's existing
lines, so the operation is additive and (with the CLI's backup) reversible. It's pure file I/O over the
same JSONL format both stores use, so it's fully unit-tested; the CLI wraps it with backup + re-projection.

The one subtlety (why this lives here, tested): the imported notes' `.md` files don't exist in the
destination vault yet, so the caller must PROTECT their ids from deletion-reconciliation (which would
otherwise tombstone them as "user-deleted") — `import_index_records` returns exactly that id set.
"""

from __future__ import annotations

import json
from pathlib import Path


def _record_note_id(record: dict[str, object]) -> str | None:
    """The note id an index record concerns: the note itself, an edge's source, or the event target."""
    kind = record.get("kind")
    if kind == "note":
        note = record.get("note")
        return str(note["id"]) if isinstance(note, dict) and "id" in note else None
    if kind == "edge":
        edge = record.get("edge")
        return str(edge["source_id"]) if isinstance(edge, dict) and "source_id" in edge else None
    note_id = record.get("note_id")
    return str(note_id) if note_id is not None else None


def import_index_records(src_index: Path, dest_index: Path, skip_note_ids: set[str]) -> set[str]:
    """Append source index records whose note isn't already in the destination; return imported note ids.

    Records for a note id in `skip_note_ids` are left out (idempotent: re-running imports nothing new,
    and a content-addressed id collision is a genuine duplicate). The destination's existing lines are
    never touched — records are only appended. The returned note-id set is what the caller must protect
    from deletion-reconciliation during re-projection (their `.md` files don't exist yet)."""
    imported: set[str] = set()
    if not src_index.exists():
        return imported
    keep: list[str] = []
    for line in src_index.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        note_id = _record_note_id(record)
        if note_id is not None and note_id in skip_note_ids:
            continue  # destination already has this note → skip its events
        keep.append(line)
        if record.get("kind") == "note" and note_id is not None:
            imported.add(note_id)
    if keep:
        with dest_index.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(keep) + "\n")
    return imported


def import_inbox_records(src_inbox: Path, dest_inbox: Path, skip_ids: set[str]) -> int:
    """Append source `inbox.jsonl` originals not already in the destination; return the count imported.

    The verbatim captures must come along so each imported note can render its "Source (original)"
    block and survive deletion-reconciliation. Deduped by original id; append-only."""
    if not src_inbox.exists():
        return 0
    keep: list[str] = []
    for line in src_inbox.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        original_id = record.get("id")
        if original_id is not None and str(original_id) in skip_ids:
            continue
        keep.append(line)
    if keep:
        with dest_inbox.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(keep) + "\n")
    return len(keep)
