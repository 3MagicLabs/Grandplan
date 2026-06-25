# SPEC — Agent intake: directives + playbooks (ROADMAP theme J)

> The in-house path for "send content + an instruction to my agent, and let it enrich and act."
> The user's headline scenario: *while scrolling Instagram, send a post to my agent — "find this
> person and their company and projects, add what they're working on to my notes, find a connection
> to what I can do, and if you can get started, go ahead."* This is the offline spine; the networked
> pieces it enables are separate opt-in connectors (below), so the core stays offline-by-default.

## Why in-house (vs. openclaw / Claude Cowork)
Those frameworks prove the loop is possible. Doing it in-house means the loop runs against **our**
append-only graph with **our** invariants: every agent action is an event (lossless/append-only,
QAS-2), the whole thing works offline (QAS-1), and the agent uses tools we already built and gated
(`VaultWrite` write tools + `VaultQuery` read/search). The directive layer is the only new primitive.

## The loop
1. **Intake** — content + an instruction arrive as a `Directive` (append-only). The instruction is
   either an ad-hoc prompt or a named **Playbook** (a reusable preset). `grandplan directive add`
   enqueues one; the eventual phone→agent transport just calls the same path.
2. **Pull** — an agent over MCP (`grandplan mcp --directives`) calls `list_directives`, reads the
   content + instruction.
3. **Fulfil** — the agent uses the existing tools: `search_notes` (find a connection), `propose_note`
   / `extract_entities` / `place` / `set_status` (capture what they're working on, link it, start a
   task). Every write is an event; no note is mutated.
4. **Complete** — the agent calls `complete_directive`; the directive drops out of `pending()`.

## Contracts

### `core/directive.py` (pure, offline, gated)
- `Directive(id, content, instruction, created, playbook="", done=False)` — `id` content-addressed
  over (content, instruction, created) so identical re-sends dedupe; `done` is *derived*.
- `Playbook(name, description, prompt)` + `PLAYBOOKS` registry. Built-ins: `profile-and-connect`
  (the headline scenario), `capture-and-file`, `extract-actions`.
- `resolve_instruction(playbook="", prompt="") -> (instruction, playbook)` — prompt overrides; unknown
  playbook → `ValueError`.
- `DirectiveStore` port + `InMemoryDirectiveStore` (gated reference) + `JsonlDirectiveStore`
  (append-only: a `directive` record per intake, a `done` record per completion; state replayed).
- `DIRECTIVE_TOOLS` + `dispatch_directive(store, name, args)` — `list_directives`, `complete_directive`.

### MCP — `adapters/mcp_server.py`
`tools_for(..., directives_enabled=...)` and `route(query, write, name, args, directives=None)` add a
third capability tier. Directive tools route only when a store is passed — **off by default**, like
writes. `grandplan mcp --directives` enables them.

### CLI
- `grandplan directive add -o <vault> [--content FILE|-] [--playbook NAME | --prompt TEXT]` — enqueue.
- `grandplan directive list -o <vault>` — show pending.

## Invariants
- **Offline (QAS-1):** the directive store + dispatch are pure/local; no egress. The networked
  transport and web research are *separate* opt-in connectors and do not live in this module.
- **Append-only (QAS-2):** directives and completions are events; `done` is derived, never an in-place
  mutation. Re-sending identical content is idempotent.
- **Capability-gated:** directive tools are off until `--directives`, mirroring `--write`.

## Transport — HTTP intake (chosen 2026-06-20) ✅ DELIVERED
`adapters/http_intake.py`: a tiny stdlib HTTP server. `POST /directive` with
`{content, playbook?, prompt?}` → enqueues a `Directive`, returns `{id, playbook}`. The
request-handling logic (`handle_intake`) is pure + gated (auth, validation, playbook resolution,
enqueue); the socket server (`serve_intake`) is the thin shell. `grandplan serve -o <vault>
[--host H] [--port P] [--token T]`.
- **Security:** binds **127.0.0.1 by default**. A routable `--host` is *refused without a `--token`*
  (else anyone on the network could enqueue). The token is checked constant-time (`hmac.compare_digest`)
  as `Authorization: Bearer <token>`. Offline: it only *receives* + stores locally; no egress.
- **Phone use:** a phone shortcut POSTs to `http://<host>:<port>/directive` over the LAN/VPN with the
  bearer token. The agent then pulls via `grandplan mcp --directives`.

## Deferred (still the user's open decisions)
- **Live web research.** Chosen *fully offline for now* (2026-06-20) — no `Researcher` connector yet;
  the agent enriches from the content + the existing vault. A networked, opt-in, egress-flagged
  `Researcher` port remains the future path; the core egress test keeps guarding the offline path.
- **Auto-run.** A daemon that watches `pending()` and dispatches to a local agent automatically
  (vs. the user running the agent). Builds on this spine once research is in scope.
