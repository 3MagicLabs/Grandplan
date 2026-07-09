"""Remote-capture intake (#37, LAN-first): POST /capture — text + media from your phone → a note.

The second route on the intake server: where `/directive` queues work for an agent, `/capture`
runs the NORMAL organize pipeline immediately — send a thought, a voice note, an image, or a
social-post link + comment from a phone on your wifi, and it lands in the vault like a hotkey
capture. Three wire formats, one pipeline (`handle_capture_request` dispatches on Content-Type):
- **multipart/form-data** — the phone-friendly path: a share-sheet shortcut attaches the raw
  shared file plus an optional caption, no base64/JSON gymnastics (text fields content/text/
  caption/note; file parts become attachments).
- **application/x-www-form-urlencoded** — a text-only Form (what iOS Shortcuts sends for a
  link/thought with no file): `content=...&text=...`.
- **application/json** — `{"content": str?, "attachments": [{"name": str, "data": <base64>}]?}`.
Either way, at least one of content / attachments is required.

Security posture (same as `/directive`, verified by tests): token-gated pre-body-read, size caps
enforced BEFORE reading, attachment names sanitized against path traversal, extensions
allow-listed, binds 127.0.0.1 unless a token is set. LAN-only by design for now: reachable on
your wifi via `--host <lan-ip> --token …`; the WireGuard/Headscale tunnel extends the same
endpoint beyond the LAN later with zero code change (docs/notes/REMOTE-CAPTURE-TRANSPORT.md).

Lossless: media bytes are saved verbatim into the vault's `attachments/` folder and referenced
from the capture text (so the deterministic resource extractor records them); a voice note is
transcribed OFFLINE (local Whisper) and the transcript becomes capture text — the audio stays.
The handling logic is pure (injected save/transcribe/organize); the socket shell reuses
`http_intake.serve_intake`.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from grandplan.adapters.http_intake import IntakeResult

logger = logging.getLogger(__name__)

MAX_CAPTURE_BODY_BYTES = 25 * 1024 * 1024  # whole request (base64 inflates ~4/3)
MAX_ATTACHMENT_BYTES = 16 * 1024 * 1024  # one decoded file
_ALLOWED_EXT = frozenset(
    {
        ".ogg",
        ".opus",
        ".m4a",
        ".mp3",
        ".wav",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".pdf",
        ".txt",
        ".md",
    }
)
AUDIO_EXT = frozenset({".ogg", ".opus", ".m4a", ".mp3", ".wav"})
_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._ -]")


@dataclass(frozen=True)
class CaptureAttachment:
    """One decoded, validated attachment: a safe basename + its verbatim bytes."""

    name: str
    data: bytes

    @property
    def suffix(self) -> str:
        return "." + self.name.rsplit(".", 1)[1].lower() if "." in self.name else ""


def safe_name(raw: str) -> str:
    """A traversal-proof basename: path components stripped (both separators), odd chars removed.

    `../../etc/passwd` or `..\\..\\boot.ini` must never escape the attachments folder — only the
    final component survives, leading dots dropped, and anything outside a conservative charset
    replaced. Raises ValueError when nothing safe remains.
    """
    base = PureWindowsPath(PurePosixPath(raw).name).name  # strip / then \ components
    cleaned = _SAFE_CHARS.sub("_", base).lstrip(". ").strip()
    if not cleaned:
        raise ValueError(f"attachment name {raw!r} is not usable")
    return cleaned


def parse_capture(payload: dict[str, object]) -> tuple[str, tuple[CaptureAttachment, ...]]:
    """Validate + decode a /capture payload (raises ValueError with an actionable message)."""
    content_raw = payload.get("content")
    content = content_raw.strip() if isinstance(content_raw, str) else ""
    raw_attachments = payload.get("attachments") or []
    if not isinstance(raw_attachments, list):
        raise ValueError('"attachments" must be a list')
    attachments: list[CaptureAttachment] = []
    for item in raw_attachments:
        if not isinstance(item, dict):
            raise ValueError("each attachment must be an object with name + data")
        name = safe_name(str(item.get("name") or ""))
        suffix = "." + name.rsplit(".", 1)[1].lower() if "." in name else ""
        if suffix not in _ALLOWED_EXT:
            raise ValueError(f"attachment type {suffix or '(none)'} not allowed")
        try:
            data = base64.b64decode(str(item.get("data") or ""), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"attachment {name!r}: invalid base64 data") from exc
        if not data:
            raise ValueError(f"attachment {name!r} is empty")
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"attachment {name!r} exceeds {MAX_ATTACHMENT_BYTES} bytes")
        attachments.append(CaptureAttachment(name=name, data=data))
    if not content and not attachments:
        raise ValueError("nothing to capture: provide content and/or attachments")
    return content, tuple(attachments)


_TEXT_FIELDS = frozenset({"content", "text", "caption", "note"})


def parse_multipart_capture(
    body: bytes, content_type: str
) -> tuple[str, tuple[CaptureAttachment, ...]]:
    """Validate + decode a `multipart/form-data` /capture upload (raises ValueError on bad input).

    This is the phone-friendly path (#37): a share-sheet shortcut attaches the raw shared file —
    a photo, a voice memo, a document — plus an optional caption, with NO client-side base64 or
    nested JSON. Text fields named content/text/caption/note become the note's thoughts; every
    file part becomes an attachment. The SAME security rules as the JSON path apply — name
    sanitised against traversal, extension allow-listed, per-file size cap — and the return shape
    is identical, so the rest of the pipeline (`_process_capture`) is unchanged.
    """
    from email.parser import BytesParser
    from email.policy import default

    # email.parser wants headers; prepend just the Content-Type so it can find the boundary.
    prefixed = b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body
    message = BytesParser(policy=default).parsebytes(prefixed)
    if not message.is_multipart():
        raise ValueError("expected a multipart/form-data body")
    content_parts: list[str] = []
    attachments: list[CaptureAttachment] = []
    for part in message.iter_parts():
        # get_payload(decode=True) is bytes for a leaf form-data part (None for a nested multipart,
        # which /capture doesn't use) — narrow it so the type is bytes throughout.
        decoded = part.get_payload(decode=True)
        payload = decoded if isinstance(decoded, bytes) else b""
        filename = part.get_filename()
        if filename:
            name = safe_name(filename)
            suffix = "." + name.rsplit(".", 1)[1].lower() if "." in name else ""
            if suffix not in _ALLOWED_EXT:
                raise ValueError(f"attachment type {suffix or '(none)'} not allowed")
            if not payload:
                raise ValueError(f"attachment {name!r} is empty")
            if len(payload) > MAX_ATTACHMENT_BYTES:
                raise ValueError(f"attachment {name!r} exceeds {MAX_ATTACHMENT_BYTES} bytes")
            attachments.append(CaptureAttachment(name=name, data=payload))
            continue
        field = part.get_param("name", header="content-disposition")
        if field in _TEXT_FIELDS:
            text = payload.decode("utf-8", errors="replace").strip()
            if text:
                content_parts.append(text)
    content = "\n\n".join(content_parts)
    if not content and not attachments:
        raise ValueError("nothing to capture: provide content and/or a file")
    return content, tuple(attachments)


def parse_urlencoded_capture(body: bytes) -> tuple[str, tuple[CaptureAttachment, ...]]:
    """Validate an `application/x-www-form-urlencoded` /capture body (text only; raises ValueError).

    What an iOS Shortcut "Form" with a text field sends (and many simple HTTP clients) — a plain
    `content=...&text=...`. A form only switches to multipart/form-data when it carries a FILE, so a
    text/link share arrives urlencoded; without this branch it fell to the JSON parser and 400'd
    ("invalid JSON body"). No binary attachments are possible in this encoding — share a file and
    the client sends multipart instead (handled by `parse_multipart_capture`).
    """
    from urllib.parse import parse_qsl

    pairs = parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    parts = [value.strip() for key, value in pairs if key in _TEXT_FIELDS and value.strip()]
    content = "\n\n".join(parts)
    if not content:
        raise ValueError("nothing to capture: provide content")
    return content, ()


def compose_capture_text(
    content: str,
    saved: list[tuple[CaptureAttachment, str]],
    transcripts: dict[str, str],
) -> str:
    """The text the organize pipeline sees: thoughts + transcripts + attachment references (pure).

    Attachment paths go INTO the text so the existing deterministic resource extractor records
    them as file resources on the note — no new resource plumbing, and the note links its media.
    """
    parts: list[str] = []
    if content:
        parts.append(content)
    for attachment, path in saved:
        transcript = transcripts.get(attachment.name, "")
        if transcript:
            parts.append(f"Voice note ({attachment.name}): {transcript}")
    if saved:
        refs = "\n".join(f"- {path}" for _a, path in saved)
        parts.append(f"Attachments:\n{refs}")
    return "\n\n".join(parts)


def handle_capture_request(
    raw: bytes,
    content_type: str,
    *,
    save: Callable[[str, bytes], str],
    organize: Callable[[str], str | None],
    transcribe: Callable[[str], str | None] | None = None,
) -> IntakeResult:
    """The one /capture entry the server calls — accepts ANY of three wire formats, one pipeline.

    - `multipart/form-data` — a share-sheet shortcut attaching a raw file (+ optional caption);
    - `application/x-www-form-urlencoded` — a text-only Form (what iOS Shortcuts sends for a
      link/thought with no file);
    - `application/json` — the original body, with base64 attachments.
    All decode to the same `(content, attachments)` and run the identical save → transcribe →
    organize pipeline. Auth + size gating already happened in the server precheck; a malformed body
    is a clean 400, never a crash.
    """
    try:
        content, attachments = parse_capture_request(raw, content_type)
    except ValueError as exc:
        return IntakeResult(400, {"error": str(exc)})
    return _process_capture(
        content, attachments, save=save, organize=organize, transcribe=transcribe
    )


def parse_capture_request(
    raw: bytes, content_type: str
) -> tuple[str, tuple[CaptureAttachment, ...]]:
    """Decode a /capture body by Content-Type into `(content, attachments)`; raises ValueError.

    The FAST, synchronous half of a capture (validate + decode). Splitting it out lets a server
    reply immediately — 400 on a bad body, otherwise accept — and defer the slow save/transcribe/
    organize to a background worker, so a phone's HTTP client doesn't time out waiting for the
    local-LLM organize (which drops the connection mid-response: WinError 10053)."""
    from grandplan.adapters.http_intake import parse_payload

    mime = content_type.split(";", 1)[0].strip().lower()
    if mime == "multipart/form-data":
        return parse_multipart_capture(raw, content_type)
    if mime == "application/x-www-form-urlencoded":
        return parse_urlencoded_capture(raw)
    return parse_capture(parse_payload(raw))


def process_capture(
    content: str,
    attachments: tuple[CaptureAttachment, ...],
    *,
    save: Callable[[str, bytes], str],
    organize: Callable[[str], str | None],
    transcribe: Callable[[str], str | None] | None = None,
) -> IntakeResult:
    """Public alias for the save → transcribe → organize half (a server runs it in the background
    after `parse_capture_request` has validated + the fast reply has been sent)."""
    return _process_capture(
        content, attachments, save=save, organize=organize, transcribe=transcribe
    )


def handle_capture(
    payload: dict[str, object],
    *,
    save: Callable[[str, bytes], str],
    organize: Callable[[str], str | None],
    transcribe: Callable[[str], str | None] | None = None,
) -> IntakeResult:
    """Process one authenticated JSON /capture payload (pure orchestration; IO is injected).

    Kept as the JSON-body entry (and back-compat seam); `handle_capture_request` dispatches the
    wire format. `save(name, data) -> stored path`, `transcribe(path) -> text|None` (None/absent =
    keep audio as attachment only), `organize(text) -> note id|None`.
    """
    try:
        content, attachments = parse_capture(payload)
    except ValueError as exc:
        return IntakeResult(400, {"error": str(exc)})
    return _process_capture(
        content, attachments, save=save, organize=organize, transcribe=transcribe
    )


def _process_capture(
    content: str,
    attachments: tuple[CaptureAttachment, ...],
    *,
    save: Callable[[str, bytes], str],
    organize: Callable[[str], str | None],
    transcribe: Callable[[str], str | None] | None,
) -> IntakeResult:
    """Save attachments verbatim → transcribe audio → organize the composed text (shared core)."""
    try:
        saved: list[tuple[CaptureAttachment, str]] = []
        transcripts: dict[str, str] = {}
        for attachment in attachments:
            path = save(attachment.name, attachment.data)
            saved.append((attachment, path))
            if transcribe is not None and attachment.suffix in AUDIO_EXT:
                text = transcribe(path)
                if text:
                    transcripts[attachment.name] = text
        note_id = organize(compose_capture_text(content, saved, transcripts))
    except Exception:  # noqa: BLE001 - disk full, bad vault path, pipeline error
        # #6 discipline: a failed capture must produce BOTH a traceback (file log) and a client
        # response — found live: an unhandled error here left the phone hanging with no reply.
        logger.exception("capture handling failed")
        return IntakeResult(500, {"error": "capture failed on the server; see the log"})
    return IntakeResult(
        201,
        {
            "note": note_id,
            "attachments": [path for _a, path in saved],
            "transcribed": sorted(transcripts),
        },
    )
