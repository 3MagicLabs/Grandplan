# SPEC — Agent-operable vault: read API + local MCP server (ROADMAP theme A, step 1)

> The unifying keystone: let AI agents **read, search, and distill** the knowledge graph over a
> local, offline protocol. This slice is **read-only**; append-only **write** tools (enrich / place /
> set-status / propose-note) are the immediate follow-up (step 2), reusing the existing event ops.

## Goal

A local **MCP server** (`grandplan mcp -o <vault>`) exposes the vault to any MCP-speaking agent
(Claude Desktop, local agents) over **stdio** — zero network egress (QAS-1). The same operations are
available as a pure, testable `VaultQuery` facade so the core logic is gated without the `mcp` dep.

## Contracts

### `core/query.py` — `VaultQuery` (pure, offline, JSON-serializable returns)
A facade over `(repo, originals, embedder)` returning plain dicts/lists (agent-friendly):
- `list_notes()` → `[{id, title, type, status, horizon, tags, due}]` (derived current notes).
- `get_note(note_id)` → full note: the above + `body`, the **verbatim original**, `resources`,
  `history` (event summaries), and outgoing `links` `[{kind, target_id, target_title}]`; `None` if unknown.
- `search_notes(query, limit=5)` → `[{id, title, type, score}]` by embedding similarity (offline embedder).
- `get_plan()` → `{now, blocked:[{note, blocked_by}], needs_review, cycle}` (from `planner.build_plan`).
- `get_masterplan()` → `{roots:[{id,title,type,horizon,children:[…]}]}` (horizon-stratified hierarchy).
- `get_graph()` → the JSON graph (`graph.to_graph`).
- `doctor()` → the health report (`report.build_run_report` as a dict).

### `core/query.py` — tool registry + dispatch (pure; the MCP layer is a thin shell)
- `TOOLS: tuple[ToolSpec, ...]` — each `{name, description, input_schema}` (JSON Schema), so schemas
  are defined and **tested** in the core, independent of `mcp`.
- `dispatch(query, name, arguments) -> object` — routes a tool call to the matching `VaultQuery`
  method; raises `ValueError` on an unknown tool or a missing required argument (validated centrally).

### `adapters/mcp_server.py` — the MCP shell (lazy-imported optional dep)
- `run_stdio_server(query)` — lazily `import mcp`, registers `TOOLS` (list-tools), routes `call-tool`
  through `dispatch`, and serves over **stdio**. Lazy import so the core/gate never needs `mcp`
  (`pip install grandplan[mcp]`). Read-only ⇒ no mutation, no vault writes.

### CLI — `grandplan mcp -o <vault> [--embeddings]`
Loads the persistent index (repo + originals), builds `VaultQuery`, runs the stdio server. Clear
install error if `mcp` is missing (mirrors the GUI's PySide6 handling). `--embeddings` must match the
embedder the vault was built with (so `search_notes` ranks correctly).

## Invariants
- **Offline (QAS-1):** stdio transport only; no sockets. `VaultQuery` is pure (no IO beyond the
  injected repo/originals). The egress test stays green.
- **Read-only here:** no tool mutates the vault; agent writes are a separate, append-only PR.
- **Hermetic gate:** `mcp` is an optional, lazily-imported extra; `VaultQuery`/`TOOLS`/`dispatch` are
  fully unit-tested with the in-memory repo and offline embedder.

## Next (step 2 — agent writes, append-only)
`propose_note`, `record_edit`, `set_status`, `add_edge`/`place`, `add_resource` as MCP **write** tools
— each an event (no note mutated), reusing the PR-A…PR-G operations; guarded + idempotent.
