"""Remote-capture intake (#37, LAN-first): POST /capture logic + its security properties.

The socket shell is a thin no-cover wrapper; everything that can go wrong — traversal names,
disallowed types, oversized/bogus data, auth-before-body-read, per-route caps — is pinned here.
"""

from __future__ import annotations

import base64

import pytest

from grandplan.adapters.capture_intake import (
    MAX_ATTACHMENT_BYTES,
    MAX_CAPTURE_BODY_BYTES,
    handle_capture,
    parse_capture,
    safe_name,
)
from grandplan.adapters.http_intake import MAX_BODY_BYTES, precheck_routes


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# -- name sanitisation: nothing may escape the attachments folder ---------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("voice.ogg", "voice.ogg"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\boot.ini", "boot.ini"),
        ("dir/sub/photo.jpg", "photo.jpg"),
        (".hidden.png", "hidden.png"),
        ("we!rd $name?.md", "we_rd _name_.md"),
    ],
)
def test_safe_name_strips_traversal_and_odd_chars(raw: str, expected: str) -> None:
    assert safe_name(raw) == expected


def test_safe_name_rejects_unusable_names() -> None:
    for raw in ("", "...", "///", "  "):
        with pytest.raises(ValueError):
            safe_name(raw)


# -- payload validation ----------------------------------------------------------------------------


def test_parse_capture_decodes_content_and_attachments() -> None:
    content, attachments = parse_capture(
        {"content": "thoughts", "attachments": [{"name": "v.ogg", "data": _b64(b"audio")}]}
    )
    assert content == "thoughts"
    assert attachments[0].name == "v.ogg" and attachments[0].data == b"audio"
    assert attachments[0].suffix == ".ogg"


@pytest.mark.parametrize(
    "payload",
    [
        {},  # nothing at all
        {"content": "   "},  # blank content, no attachments
        {"content": "x", "attachments": "nope"},  # attachments not a list
        {"attachments": [{"name": "a.exe", "data": _b64(b"x")}]},  # disallowed type
        {"attachments": [{"name": "a.png", "data": "not-base64!!"}]},  # bogus encoding
        {"attachments": [{"name": "a.png", "data": ""}]},  # empty file
    ],
)
def test_parse_capture_rejects_bad_payloads(payload: dict) -> None:
    with pytest.raises(ValueError):
        parse_capture(payload)


def test_parse_capture_enforces_per_attachment_cap() -> None:
    huge = _b64(b"x" * (MAX_ATTACHMENT_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds"):
        parse_capture({"attachments": [{"name": "big.png", "data": huge}]})


# -- handling: save + transcribe + organize --------------------------------------------------------


def _run(payload: dict, *, transcribe=None):  # type: ignore[no-untyped-def]
    saved: dict[str, bytes] = {}
    organized: list[str] = []

    def save(name: str, data: bytes) -> str:
        saved[name] = data
        return f"/vault/attachments/{name}"

    def organize(text: str) -> str:
        organized.append(text)
        return "1 note(s) organized"

    result = handle_capture(payload, save=save, organize=organize, transcribe=transcribe)
    return result, saved, organized


def test_capture_voice_note_transcribes_and_references_the_audio() -> None:
    payload = {
        "content": "context from my phone",
        "attachments": [{"name": "memo.ogg", "data": _b64(b"opusbytes")}],
    }
    result, saved, organized = _run(payload, transcribe=lambda path: "the spoken words")
    assert result.status == 201
    assert saved["memo.ogg"] == b"opusbytes"  # verbatim bytes kept (lossless)
    text = organized[0]
    assert "context from my phone" in text
    assert "the spoken words" in text  # transcript became capture text
    assert "/vault/attachments/memo.ogg" in text  # audio referenced as a resource
    assert result.body["transcribed"] == ["memo.ogg"]


def test_capture_image_plus_thoughts_without_transcriber() -> None:
    payload = {
        "content": "instagram post about workshops https://instagram.com/p/abc plus my thoughts",
        "attachments": [{"name": "shot.png", "data": _b64(b"png")}],
    }
    result, saved, organized = _run(payload, transcribe=None)
    assert result.status == 201
    assert "instagram.com/p/abc" in organized[0]  # link stays in text → resource extractor
    assert "/vault/attachments/shot.png" in organized[0]
    assert result.body["transcribed"] == []


def test_capture_text_only_and_bad_payload_status_codes() -> None:
    ok, _saved, organized = _run({"content": "just a thought"})
    assert ok.status == 201 and organized == ["just a thought"]
    bad, saved, organized2 = _run({"attachments": [{"name": "x.exe", "data": _b64(b"x")}]})
    assert bad.status == 400
    assert not saved and not organized2  # rejected payloads never touch disk or the pipeline


def test_failed_transcription_keeps_the_audio_capture() -> None:
    payload = {"attachments": [{"name": "memo.ogg", "data": _b64(b"opus")}]}
    result, _saved, organized = _run(payload, transcribe=lambda path: None)
    assert result.status == 201  # no transcript, but the audio attachment still becomes a note
    assert "memo.ogg" in organized[0]


# -- routing security: per-route caps, auth before body --------------------------------------------


def test_precheck_routes_caps_and_auth() -> None:
    routes = {"/directive": MAX_BODY_BYTES, "/capture": MAX_CAPTURE_BODY_BYTES}
    assert precheck_routes("/nope", 10, "", "", routes).status == 404  # type: ignore[union-attr]
    # each route enforces its OWN cap, pre-body-read
    assert precheck_routes("/directive", MAX_BODY_BYTES + 1, "", "", routes).status == 413  # type: ignore[union-attr]
    assert precheck_routes("/capture", MAX_BODY_BYTES + 1, "", "", routes) is None  # fits capture
    assert precheck_routes("/capture", MAX_CAPTURE_BODY_BYTES + 1, "", "", routes).status == 413  # type: ignore[union-attr]
    # token gates BOTH routes before any body is read
    assert precheck_routes("/capture", 10, "", "secret", routes).status == 401  # type: ignore[union-attr]
    assert precheck_routes("/capture", 10, "Bearer secret", "secret", routes) is None


def test_server_side_failure_returns_500_never_a_silent_hang() -> None:
    # Found live: an exception in save/organize left the client with NO response at all.
    def boom_save(name: str, data: bytes) -> str:
        raise OSError("disk full")

    result = handle_capture(
        {"attachments": [{"name": "a.png", "data": _b64(b"x")}]},
        save=boom_save,
        organize=lambda text: "n",
        transcribe=None,
    )
    assert result.status == 500
    assert "error" in result.body  # the phone always gets an answer
