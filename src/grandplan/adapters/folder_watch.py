"""Folder-watch capture — turn files dropped into a folder into agent directives (ROADMAP theme H).

An offline capture surface: point grandplan at a folder (e.g. a synced "inbox" you drop text/markdown
into from any device), and each new file becomes an append-only `Directive` an agent later fulfils —
reusing the directive/playbook spine. The scan + enqueue LOGIC (`scan_folder`) is pure and gated; the
continuous poll loop (`watch_folder`) is the thin shell. Zero egress: it only reads local files.

Capture-by-path: each file is captured once per path (tracked in a `seen` set), so re-polling doesn't
re-enqueue it. Identical content is also de-duplicated by the directive store's content-addressing.
"""

from __future__ import annotations

import time
from pathlib import Path

from grandplan.core.directive import Directive, DirectiveStore

_CAPTURE_SUFFIXES = (".txt", ".md", ".markdown")


def scan_folder(
    folder: Path,
    store: DirectiveStore,
    *,
    created: str,
    instruction: str,
    playbook: str,
    seen: set[str],
) -> list[str]:
    """Enqueue a directive for each new capture file in `folder`; return the new directive ids.

    Considers `*.txt`/`*.md`/`*.markdown` files only, in sorted order (deterministic). A file already
    in `seen` (by absolute path) is skipped; processed paths are added to `seen` (mutated in place),
    so a subsequent scan won't re-enqueue it. Empty files are marked seen but enqueue nothing. Missing
    folder → no-op.
    """
    if not folder.is_dir():
        return []
    enqueued: list[str] = []
    for path in sorted(folder.iterdir()):
        key = str(path.resolve())
        if key in seen or path.suffix.lower() not in _CAPTURE_SUFFIXES or not path.is_file():
            continue
        seen.add(key)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # unreadable/binary → skip (already marked seen so we don't retry it)
        if not content.strip():
            continue
        directive = Directive.create(content, instruction, created, playbook=playbook)
        store.add(directive)
        enqueued.append(directive.id)
    return enqueued


def watch_folder(  # pragma: no cover - long-running poll loop; scan logic is tested via scan_folder
    folder: Path,
    store: DirectiveStore,
    *,
    instruction: str,
    playbook: str,
    interval: float,
    now: object,
) -> None:
    """Poll `folder` every `interval` seconds, enqueuing a directive per new file, until interrupted.

    `now` is a zero-arg callable returning an ISO timestamp (injected; no hidden clock in the loop).
    """
    seen: set[str] = set()
    print(f"watching {folder} every {interval}s (Ctrl+C to stop)")
    try:
        while True:
            ids = scan_folder(
                folder,
                store,
                created=str(now()),  # type: ignore[operator]
                instruction=instruction,
                playbook=playbook,
                seen=seen,
            )
            for directive_id in ids:
                print(f"queued directive {directive_id}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("stopped watching")
