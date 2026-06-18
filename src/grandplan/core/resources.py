"""Resource references — external links, files, images, and placeholder expectations (PR-D, ADR-0008).

A capture often names a real artifact (a website, a GitHub repo, a PDF/image, a local file) or one
the user still needs to make ("a resume website"). A `Resource` models that reference; the
deterministic `extract_resources` pulls them out of the verbatim capture text (the LLM organizer
proposes richer ones). Resources are a creation-time field on the note (like `status`) — the
`resource` *event* kind + attach-to-an-existing-note flow are PR-E.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tiff", ".ico")

# An http(s) URL (stops at whitespace or a closing bracket/quote).
_URL = re.compile(r"""https?://[^\s<>"')\]]+""")
# A local file path: a real path prefix (`/`, `~/`, `./`, `../`, `C:\`) at a token boundary, then a
# file extension. The leading `(?<!\S)` stops it from biting a slash in the middle of another token.
_PATH = re.compile(r"""(?<!\S)(?:[A-Za-z]:\\|~?/|\.\.?/)[^\s<>"'\[\]]*\.\w{1,6}""")
# Creation-intent → a placeholder. The artifact noun follows the verb either directly ("build app")
# or after an article + up to two adjectives ("create a landing page"). Requiring an *article* before
# any adjectives is what rejects the "make sure the page loads" idiom ("sure" is not an article).
_ARTIFACT = (
    r"doc(?:ument)?|page|site|website|resume|cv|deck|slides?|pdf|report|spreadsheet|sheet|"
    r"diagram|mockup|design|essay|letter|presentation|paper|plan|proposal|readme|app|script"
)
_PLACEHOLDER = re.compile(
    rf"\b(?:make|create|build|write|draft|design|need)\s+"
    rf"(?:(?:a|an|the|my|some|new)\s+(?:\w+\s+){{0,2}}?)?"
    rf"(?P<art>{_ARTIFACT})\b",
    re.IGNORECASE,
)
_URL_TRAILING = ".,;:!?)]}>\"'"


class ResourceKind(str, Enum):
    """How a reference renders in Obsidian (SPEC §PR-D)."""

    LINK = "link"  # external URL → [label](url)
    IMAGE = "image"  # image URL or path → ![label](url) / ![[ref]]
    FILE = "file"  # local file path / vault name → [label](path) / [[ref]]
    PLACEHOLDER = "placeholder"  # an expected, not-yet-existing artifact


@dataclass(frozen=True)
class Resource:
    """A referenced (or expected) artifact attached to a note."""

    kind: ResourceKind
    ref: str  # the URL / path, or — for a placeholder — a short artifact description
    label: str = ""  # optional display label


def _is_image(ref: str) -> bool:
    base = ref.split("?", 1)[0].split("#", 1)[0].lower()
    return base.endswith(_IMAGE_EXTS)


def extract_resources(text: str) -> tuple[Resource, ...]:
    """Pull URLs, file paths, and a placeholder expectation out of a capture (order-stable, deduped).

    URLs are extracted first and masked out before path extraction, so a URL's own slashes are never
    re-read as a separate file path.
    """
    out: list[Resource] = []
    seen: set[tuple[ResourceKind, str]] = set()

    def add(kind: ResourceKind, ref: str) -> None:
        key = (kind, ref)
        if key not in seen:
            seen.add(key)
            out.append(Resource(kind=kind, ref=ref))

    for match in _URL.finditer(text):
        ref = match.group(0).rstrip(_URL_TRAILING)
        add(ResourceKind.IMAGE if _is_image(ref) else ResourceKind.LINK, ref)

    masked = _URL.sub(" ", text)  # so the path regex can't re-match a URL's slashes
    for match in _PATH.finditer(masked):
        ref = match.group(0)
        add(ResourceKind.IMAGE if _is_image(ref) else ResourceKind.FILE, ref)

    placeholder = _PLACEHOLDER.search(masked)
    if placeholder is not None:
        add(ResourceKind.PLACEHOLDER, placeholder.group("art").lower())

    return tuple(out)
