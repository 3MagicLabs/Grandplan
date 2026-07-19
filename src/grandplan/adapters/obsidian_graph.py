"""Read the Obsidian graph filter (SPEC-SCOPE §5) — the one read of `.obsidian/graph.json`.

The mirror image of `core.project.write_obsidian_config`, which *writes* the graph's `search` field
(the Filters box). Here we *read* it back so chat can scope to whatever the user filtered to in the
graph. Best-effort and total: a missing, unreadable, or foreign config yields `None` (no scope), it
never raises — a broken graph config must not take the conversation down with it.
"""

from __future__ import annotations

import json
from pathlib import Path


def read_graph_filter(vault_dir: Path) -> str | None:
    """The current graph Filters query for `vault_dir`, or `None` if there isn't a readable one."""
    config = vault_dir / ".obsidian" / "graph.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # absent, unreadable, or not JSON
    if not isinstance(data, dict):
        return None
    search = data.get("search")
    return search if isinstance(search, str) and search.strip() else None
