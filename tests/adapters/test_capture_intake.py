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
    handle_capture_request,
    parse_capture,
    parse_multipart_capture,
    parse_urlencoded_capture,
    safe_name,
)
from grandplan.adapters.http_intake import MAX_BODY_BYTES, precheck_routes


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _multipart(
    text_fields: dict[str, str],
    file_parts: list[tuple[str, str, bytes]],
    boundary: str = "BoUnDaRy123",
) -> tuple[bytes, str]:
    """Build a real multipart/form-data body (what a phone share-sheet shortcut sends)."""
    chunks: list[bytes] = []
    for name, val in text_fields.items():
        chunks += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{name}"'.encode(),
            b"",
            val.encode("utf-8"),
        ]
    for field, filename, data in file_parts:
        chunks += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"'.encode(),
            b"Content-Type: application/octet-stream",
            b"",
            data,
        ]
    chunks += [f"--{boundary}--".encode(), b""]
    return b"\r\n".join(chunks), f"multipart/form-data; boundary={boundary}"


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


# -- multipart uploads: a phone shares a file directly, no base64/JSON ----------------------------


def test_parse_multipart_decodes_text_and_file_without_base64() -> None:
    # The whole point of #37's file-upload path: the phone attaches the raw shared file (photo,
    # voice memo) plus a caption; no client-side base64 or nested JSON.
    body, content_type = _multipart(
        {"content": "shared from instagram https://insta/p/x plus my note"},
        [("file", "photo.jpg", b"\xff\xd8rawjpegbytes")],
    )
    content, attachments = parse_multipart_capture(body, content_type)
    assert "instagram" in content
    assert len(attachments) == 1
    assert attachments[0].name == "photo.jpg"
    assert attachments[0].data == b"\xff\xd8rawjpegbytes"  # verbatim bytes, undecoded
    assert attachments[0].suffix == ".jpg"


def test_parse_multipart_applies_the_same_security_rules() -> None:
    # traversal name sanitised, and the same extension allow-list as the JSON path
    body, ct = _multipart({}, [("file", "../../evil.jpg", b"x")])
    _content, atts = parse_multipart_capture(body, ct)
    assert atts[0].name == "evil.jpg"  # traversal stripped
    bad_body, bad_ct = _multipart({}, [("file", "malware.exe", b"x")])
    with pytest.raises(ValueError, match="not allowed"):
        parse_multipart_capture(bad_body, bad_ct)
    empty_body, empty_ct = _multipart({}, [])  # no text, no files → rejected (either 400 message)
    with pytest.raises(ValueError):
        parse_multipart_capture(empty_body, empty_ct)


def test_parse_urlencoded_capture_decodes_text_fields() -> None:
    # iOS Shortcuts (and many simple HTTP clients) send a TEXT-only Form as
    # application/x-www-form-urlencoded, NOT multipart — the server must accept it.
    content, attachments = parse_urlencoded_capture(
        b"content=hello+world+https%3A%2F%2Fx.com%2Fp&other=ignored"
    )
    assert content == "hello world https://x.com/p"
    assert attachments == ()  # urlencoded can't carry binary files


def test_parse_urlencoded_capture_rejects_empty() -> None:
    with pytest.raises(ValueError, match="nothing to capture"):
        parse_urlencoded_capture(b"unrelated=x")


def test_parse_capture_request_dispatches_each_format() -> None:
    # The sync validate/decode half the server calls before replying fast + organizing in the bg.
    from grandplan.adapters.capture_intake import parse_capture_request

    c1, a1 = parse_capture_request(b"content=hi+there", "application/x-www-form-urlencoded")
    assert c1 == "hi there" and a1 == ()
    c2, a2 = parse_capture_request(b'{"content":"json note"}', "application/json")
    assert c2 == "json note" and a2 == ()
    body, ct = _multipart({"content": "cap"}, [("file", "p.png", b"png")])
    c3, a3 = parse_capture_request(body, ct)
    assert c3 == "cap" and a3[0].name == "p.png"
    with pytest.raises(ValueError):  # a bad body raises (caller turns it into a 400)
        parse_capture_request(b"not json", "application/json")


def test_handle_capture_request_accepts_urlencoded_form() -> None:
    # The exact shape an iOS Shortcut "Form" (text field) sends — must reach the pipeline, not the
    # JSON branch (which produced the 'invalid JSON body' phone error).
    organized: list[str] = []
    result = handle_capture_request(
        b"content=note+from+phone",
        "application/x-www-form-urlencoded; charset=utf-8",
        save=lambda n, d: f"/v/{n}",
        organize=lambda t: organized.append(t) or "1 note(s) organized",
    )
    assert result.status == 201
    assert organized == ["note from phone"]


def test_handle_capture_request_dispatches_json_and_multipart_to_one_pipeline() -> None:
    saved: dict[str, bytes] = {}
    organized: list[str] = []

    def save(name: str, data: bytes) -> str:
        saved[name] = data
        return f"/vault/attachments/{name}"

    def organize(text: str) -> str:
        organized.append(text)
        return "1 note(s) organized"

    # multipart voice memo → transcribed and referenced, exactly like the JSON path
    body, ct = _multipart({"content": "phone note"}, [("file", "memo.m4a", b"aacbytes")])
    result = handle_capture_request(
        body, ct, save=save, organize=organize, transcribe=lambda p: "spoken words"
    )
    assert result.status == 201
    assert saved["memo.m4a"] == b"aacbytes"
    assert "phone note" in organized[0] and "spoken words" in organized[0]
    assert result.body["transcribed"] == ["memo.m4a"]

    # same entry point still accepts the original JSON+base64 body (back-compat)
    json_body = f'{{"content":"typed","attachments":[{{"name":"a.png","data":"{_b64(b"png")}"}}]}}'
    r2 = handle_capture_request(
        json_body.encode(), "application/json", save=save, organize=organize, transcribe=None
    )
    assert r2.status == 201 and saved["a.png"] == b"png"

    # a malformed JSON body is a clean 400, never a crash
    r3 = handle_capture_request(b"not json", "application/json", save=save, organize=organize)
    assert r3.status == 400


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
