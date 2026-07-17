"""Open a vault in Obsidian, focused on the graph view (used by `grandplan up --open`).

Two pure, testable pieces — the `.obsidian/workspace.json` scaffold that makes the **graph** the
active view, and the `obsidian://open?path=…` URI — plus a thin, platform-dependent launcher
(`open_in_obsidian`) that hands the URI to the OS so Obsidian (the registered `obsidian://` handler)
opens the vault. Launching is best-effort and offline: it only invokes the local handler, opens no
network connection, and never raises into the caller.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import quote

from grandplan.core.models import Note
from grandplan.core.vault import plan_filenames

# A minimal Obsidian workspace with the GRAPH view as the single active leaf, so opening the vault
# lands on the graph. Written only into a fresh vault (never clobbers an existing workspace); if a
# future Obsidian rejects the shape it just falls back to its default view — the user clicks the graph.
_GRAPH_WORKSPACE: dict[str, object] = {
    "main": {
        "id": "grandplan-root",
        "type": "split",
        "direction": "vertical",
        "children": [
            {
                "id": "grandplan-graph",
                "type": "leaf",
                "state": {"type": "graph", "state": {}, "title": "Graph"},
            }
        ],
    },
    "active": "grandplan-graph",
    "lastOpenFiles": [],
}


def scaffold_graph_view(vault_dir: Path) -> bool:
    """Write `.obsidian/workspace.json` opening on the graph — only if absent. Returns True if written.

    Non-destructive: an existing workspace (the user's layout) is left untouched.
    """
    workspace = vault_dir / ".obsidian" / "workspace.json"
    if workspace.exists():
        return False
    workspace.parent.mkdir(parents=True, exist_ok=True)
    workspace.write_text(json.dumps(_GRAPH_WORKSPACE, indent=2), encoding="utf-8")
    return True


def obsidian_open_uri(target: Path) -> str:
    """The `obsidian://open?path=…` URI for an absolute path.

    `target` may be a **vault directory** (opens/registers the vault) or a **note file inside one**
    (opens the vault focused on that note — the hand-off `grandplan graph --open` uses to land the
    user on a note, where Obsidian's own local-graph pane does the depth and layout a terminal can't).
    """
    return f"obsidian://open?path={quote(str(target.resolve()), safe='')}"


def note_file(note_id: str, notes: Iterable[Note], vault_dir: Path) -> Path | None:
    """The rendered `.md` file for a note id, or None when unknown or not on disk.

    The id → stem map is a pure function of the note SET (`plan_filenames`), never of disk state, so
    this agrees with the `[[wikilink]]`s inside the notes themselves. Returning None for a note the
    index knows but that has no file is the honest answer, not a fallback to the vault root: it means
    the projections are stale (`rerender` fixes it), and silently opening something else would hide
    that. Shared by `grandplan graph --open` and the chat window's clickable sources.
    """
    stem = plan_filenames(notes).get(note_id)
    if stem is None:
        return None
    target = vault_dir / f"{stem}.md"
    return target if target.exists() else None


def open_in_obsidian(target: Path) -> bool:  # pragma: no cover - launches the OS URI handler
    """Hand a vault dir or note file's `obsidian://` URI to the OS handler. Best-effort; never raises."""
    uri = obsidian_open_uri(target)
    try:
        startfile = getattr(os, "startfile", None)
        if startfile is not None:  # Windows: open via the registered protocol handler
            startfile(uri)
        else:  # macOS/Linux (incl. WSL with a configured handler)
            import webbrowser

            webbrowser.open(uri)
    except OSError:
        return False
    return True
