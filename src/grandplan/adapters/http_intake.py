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
from dataclasses import dataclass

from grandplan.core.directive import Directive, DirectiveStore, resolve_instruction


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
    if token and not (provided_token and hmac.compare_digest(token, provided_token)):
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


def serve_intake(
    store: DirectiveStore, *, host: str = "127.0.0.1", port: int = 8765, token: str = ""
) -> None:  # pragma: no cover - binds a socket; the request logic is tested via handle_intake
    """Run the HTTP intake server until interrupted. POST /directive with a JSON body.

    Binds 127.0.0.1 by default (safe). Pass a routable host to reach it from another device — only do
    that together with a `token`, since the endpoint then accepts directives from the network.
    """
    from datetime import datetime, timezone
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def _reply(self, result: IntakeResult) -> None:
            encoded = json.dumps(result.body).encode("utf-8")
            self.send_response(result.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path.rstrip("/") != "/directive":
                self._reply(IntakeResult(404, {"error": "not found"}))
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = parse_payload(self.rfile.read(length))
            except ValueError as exc:
                self._reply(IntakeResult(400, {"error": str(exc)}))
                return
            auth = self.headers.get("Authorization", "")
            provided = auth[len("Bearer ") :] if auth.startswith("Bearer ") else None
            result = handle_intake(
                store,
                payload,
                datetime.now(timezone.utc).isoformat(),
                token=token,
                provided_token=provided,
            )
            self._reply(result)

        def log_message(self, *args: object) -> None:
            pass  # quiet by default

    server = ThreadingHTTPServer((host, port), _Handler)
    print(f"intake listening on http://{host}:{port}/directive (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
