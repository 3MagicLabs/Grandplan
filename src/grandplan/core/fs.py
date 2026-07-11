"""Filesystem write helpers shared by the projection writers.

`write_text_if_changed` is the core of the incremental-projection fix (perf audit P1.1/P1.4). A
projection re-derives every file's *content* on each capture, but the vast majority of files are
byte-identical to what is already on disk. Writing them anyway costs ~N file writes per capture AND
— the sharp edge — bumps each file's mtime, so a cloud-synced vault (OneDrive/Dropbox) re-uploads
the WHOLE vault after every capture. Skipping identical writes makes a capture touch only the handful
of files that actually changed, so a 10k-note vault behaves close to a fresh one and cloud sync stays
quiet. The skip is provably output-preserving: a write is elided only when the new bytes equal the
existing bytes, so the on-disk result is exactly what an unconditional write would have produced.
"""

from __future__ import annotations

from pathlib import Path


def write_text_if_changed(path: Path, content: str, *, encoding: str = "utf-8") -> bool:
    """Write `content` to `path` only when it differs from the file already there.

    Returns True if a write happened, False if the on-disk content was already identical (the file —
    and its mtime — is then left completely untouched). A missing or unreadable file falls through to
    a write. The comparison is on decoded text, so platform newline translation round-trips cleanly
    (write_text/read_text apply the same universal-newline handling on every OS).
    """
    try:
        if path.read_text(encoding=encoding) == content:
            return False
    except OSError:
        pass  # missing or unreadable → (re)write it
    path.write_text(content, encoding=encoding)
    return True
