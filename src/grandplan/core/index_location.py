"""Where grandplan keeps its rebuildable index — OUTSIDE the (possibly cloud-synced) vault.

The note index (embeddings, edges) and the verbatim inbox are *internal, rebuildable* state, not
user-facing vault content. Keeping them inside the vault means a cloud sync (OneDrive/Dropbox/iCloud)
churns and can conflict them across devices and bloats the vault. So they live under a per-vault
directory in the user's home (overridable via `GRANDPLAN_HOME`), keyed by the vault's absolute path.
The user-facing projections (`Plan.md`, `graph.json`) stay IN the vault for Obsidian.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

_LEGACY_DIRNAME = ".grandplan"


def index_dir(vault_dir: Path) -> Path:
    """The external index directory for `vault_dir` — deterministic, per-vault, outside the vault."""
    base_env = os.environ.get("GRANDPLAN_HOME")
    base = Path(base_env) if base_env else Path.home() / _LEGACY_DIRNAME
    key = hashlib.sha256(str(vault_dir.resolve()).encode("utf-8")).hexdigest()[:16]
    return base / key


def migrate_legacy_index(vault_dir: Path) -> Path:
    """Move a legacy in-vault `.grandplan/` to the external index dir, once; return the index dir.

    Idempotent and safe: a no-op when there's no legacy dir or the external dir already exists, so a
    user's already-migrated (or freshly-external) index is never clobbered.
    """
    target = index_dir(vault_dir)
    legacy = vault_dir / _LEGACY_DIRNAME
    if legacy.is_dir() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(target))
    return target
