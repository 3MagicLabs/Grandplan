"""HTTP intake — a localhost endpoint that enqueues agent directives (ROADMAP theme J transport).

The "send to my agent" transport: a tiny HTTP server you can POST content + a playbook/prompt to
(e.g. from a phone shortcut over your LAN/VPN), which enqueues a `Directive` your agent later pulls
over MCP. The request-handling LOGIC (auth, validation, playbook resolution, enqueue) is a pure
function (`handle_intake`) — fully gated; the socket server (`serve_intake`) is a thin stdlib shell.

Security: binds **127.0.0.1 by default** (override with an explicit host to reach it from the phone).
An optional shared-secret token gates every request (constant-time compared), so exposing it on a LAN
needs a credential. Offline by default: nothing is fetched; it only *receives* and stores locally.
"""

from __future__ import annotations

import hmac
import json
import logging
from dataclasses import dataclass

from grandplan.core.directive import Directive, DirectiveStore, resolve_instruction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntakeResult:
    """The HTTP status + JSON body for an intake request (pure; the shell serializes it)."""

    status: int
    body: dict[str, object]


def handle_intake(
    store: DirectiveStore,
    payload: dict[str, object],
    created: str,
    *,
    token: str = "",
    provided_token: str | None = None,
) -> IntakeResult:
    """Validate + enqueue a directive from a parsed request payload (pure, no IO beyond the store).

    `payload` = `{content, playbook?, prompt?}`. When `token` is set, `provided_token` must match it
    (constant-time). Returns 401 on auth failure, 400 on a bad request, 201 with the new id on success.
    """
    if not check_auth(token, provided_token):
        return IntakeResult(401, {"error": "unauthorized"})
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return IntakeResult(400, {"error": "content is required"})
    raw_playbook = payload.get("playbook")
    raw_prompt = payload.get("prompt")
    playbook = raw_playbook if isinstance(raw_playbook, str) else ""
    prompt = raw_prompt if isinstance(raw_prompt, str) else ""
    try:
        instruction, resolved_playbook = resolve_instruction(playbook=playbook, prompt=prompt)
    except ValueError as exc:
        return IntakeResult(400, {"error": str(exc)})
    directive = Directive.create(content, instruction, created, playbook=resolved_playbook)
    store.add(directive)
    return IntakeResult(201, {"id": directive.id, "playbook": resolved_playbook})


def parse_payload(raw: bytes) -> dict[str, object]:
    """Decode a request body into a dict (raises ValueError on malformed / non-object JSON)."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid JSON body: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


MAX_BODY_BYTES = 1 * 1024 * 1024
"""Largest request body the server will read (1 MiB). A larger declared Content-Length is rejected
with 413 *before* any bytes are read — capping memory use from a hostile or oversized request."""


def bearer_token(authorization: str) -> str | None:
    """Pull the token from an `Authorization: Bearer <token>` header value (None if absent/other scheme)."""
    prefix = "Bearer "
    return authorization[len(prefix) :] if authorization.startswith(prefix) else None


def check_auth(token: str, provided_token: str | None) -> bool:
    """Authorized iff no token is configured, or the provided token matches it (constant-time)."""
    if not token:
        return True
    return provided_token is not None and hmac.compare_digest(token, provided_token)


def precheck_request(
    path: str,
    content_length: int,
    authorization: str,
    token: str,
    *,
    max_body: int = MAX_BODY_BYTES,
) -> IntakeResult | None:
    """Body-independent gate run BEFORE the body is read; None means "read the body and handle it".

    Folds the rejections that must happen pre-read — wrong path (404), missing/oversized/garbled
    Content-Length (400/413), and failed auth (401) — so the socket shell never reads an unauthenticated
    or unbounded body. This is the fix for the read-before-auth and no-size-cap DoS amplifiers.
    """
    if path.rstrip("/") != "/directive":
        return IntakeResult(404, {"error": "not found"})
    if content_length < 0:
        return IntakeResult(400, {"error": "invalid Content-Length"})
    if content_length > max_body:
        return IntakeResult(413, {"error": "payload too large"})
    if not check_auth(token, bearer_token(authorization)):
        return IntakeResult(401, {"error": "unauthorized"})
    return None


def precheck_routes(
    path: str,
    content_length: int,
    authorization: str,
    token: str,
    routes: dict[str, int],
) -> IntakeResult | None:
    """Multi-route twin of `precheck_request`: `routes` maps path → max body bytes (#37).

    Same pre-body-read guarantees per route: unknown path 404, bad/oversized Content-Length
    400/413 (each route with its OWN cap — /capture carries media, /directive stays small), and
    auth 401 — all before a byte of body is read off the socket.
    """
    max_body = routes.get(path.rstrip("/"))
    if max_body is None:
        return IntakeResult(404, {"error": "not found"})
    return precheck_request("/directive", content_length, authorization, token, max_body=max_body)


def serve_intake(
    store: DirectiveStore,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str = "",
    capture: object = None,
) -> None:  # pragma: no cover - binds a socket; the request logic is tested via handle_intake
    """Run the HTTP intake server until interrupted. POST /directive (and /capture when wired).

    Binds 127.0.0.1 by default (safe). Pass a routable host to reach it from another device — only do
    that together with a `token`, since the endpoint then accepts requests from the network.
    `capture` (#37): a `Callable[[dict], IntakeResult]` handling POST /capture (text + attachments
    → an organized note); None keeps the server directive-only.
    """
    from datetime import datetime, timezone
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def _reply(self, result: IntakeResult) -> None:
            # One audit line per response (status + client IP, never the token or body) — the default
            # access log stays off (log_message below), so this is the sole, intentional trail.
            logger.info("intake %s from %s -> %d", self.path, self.client_address[0], result.status)
            encoded = json.dumps(result.body).encode("utf-8")
            self.send_response(result.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                length = -1  # unparseable Content-Length → precheck rejects with 400
            authorization = self.headers.get("Authorization", "")
            routes = {"/directive": MAX_BODY_BYTES}
            if capture is not None:
                from grandplan.adapters.capture_intake import MAX_CAPTURE_BODY_BYTES

                routes["/capture"] = MAX_CAPTURE_BODY_BYTES
            # bad path / oversized body / unauthorized → reply without reading the body off the socket
            early = precheck_routes(self.path, length, authorization, token, routes)
            if early is not None:
                self._reply(early)
                return
            try:
                payload = parse_payload(self.rfile.read(length))
            except ValueError as exc:
                self._reply(IntakeResult(400, {"error": str(exc)}))
                return
            if capture is not None and self.path.rstrip("/") == "/capture":
                self._reply(capture(payload))  # type: ignore[operator]
                return
            result = handle_intake(
                store,
                payload,
                datetime.now(timezone.utc).isoformat(),
                token=token,
                provided_token=bearer_token(authorization),
            )
            self._reply(result)

        def log_message(self, *args: object) -> None:
            pass  # default access log stays off; we emit our own audit line in _reply

    server = ThreadingHTTPServer((host, port), _Handler)
    print(f"intake listening on http://{host}:{port}/directive (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
