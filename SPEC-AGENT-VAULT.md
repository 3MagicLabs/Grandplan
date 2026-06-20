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

## Step 2 — agent writes, append-only (ROADMAP item 2) ✅ DELIVERED

Let agents **enrich / organize / create** safely. Every write is an **event** reusing the PR-A…PR-G
repository operations — no stored note or original is ever mutated; current state stays *derived*
(QAS-2). Offline (QAS-1): the facade is pure over the injected `(repo, originals, embedder)`, so it is
fully unit-tested without the `mcp` dep, exactly like `VaultQuery`.

### `core/write.py` — `VaultWrite` (pure, offline, JSON-serializable returns)
A facade over `(repo, originals, embedder)`. Each method **validates inputs** (unknown note / bad enum
/ empty arg / self-loop → `ValueError` with a clear message), then calls the matching idempotent repo
op, and returns `{"ok": True, "applied": bool, ...}` — `applied=False` means the op was a no-op
(idempotent: status unchanged, edit is a no-op, edge/resource already present, note already exists):
- `set_status(note_id, status)` → `repo.set_status`; `{ok, applied, note_id, status}`.
- `record_edit(note_id, *, title?, body?, tags?, due?)` → `repo.record_edit(NoteEdit)`; empty edit →
  `ValueError`; `{ok, applied, note_id}`. (Clearing a field is out of scope, per `NoteEdit`.)
- `add_resource(note_id, kind, ref, label?)` → `repo.add_resource(Resource)`; `{ok, applied, note_id}`.
- `place(source_id, target_id, kind)` → `repo.add_edge(Edge)`; rejects a self-loop; `{ok, applied}`.
- `propose_note(text, title, type, created, *, body?, tags?)` → mints an `Original.capture` (source
  `app="agent"`, caller-supplied `created` — **no hidden clock**), embeds via the injected offline
  embedder, `Note.from_proposed` (deterministic id), `repo.add_note`; `{ok, applied, note_id}`.

### `core/write.py` — write tool registry + dispatch
- `WRITE_TOOLS: tuple[ToolSpec, ...]` — JSON-Schema for each write tool (reuses `query.ToolSpec`).
- `dispatch_write(write, name, arguments) -> object` — routes a write call; `ValueError` on unknown
  tool or missing/invalid required argument (validated centrally, mirroring `query.dispatch`).

### MCP wiring — `adapters/mcp_server.py` + CLI `grandplan mcp --write`
`run_stdio_server(query, write=None)` registers the read `TOOLS` plus (when `write` is given) the
`WRITE_TOOLS`, routing each `call-tool` to read- then write-dispatch. **Read-only by default**;
`grandplan mcp -o <vault> --write` opts into agent writes (the safe default keeps writes off until
asked). Writes persist to `index.jsonl`; Obsidian projections (`.md`/`Plan.md`/`graph.json`) refresh
on the next `grandplan regenerate`/`rerender` (derived-state model).

## Step 3 — entity extraction + `involves` edges (ROADMAP item 3) ✅ DELIVERED

`core/entities.py`: an `EntityExtractor` port (Strategy) + the deterministic offline
`HeuristicEntityExtractor` (≥2-word proper nouns, org-suffixed names, `@handles`; conservative,
deduped case-insensitively) + `materialize_entities`, which turns each mention into an `entity` note
joined to the source note by an `involves` edge. Append-only & idempotent: entity ids are
content-addressed by name (so the same person/org collapses to one node), and `add_note`/`add_edge`
are idempotent. `entity` nodes are excluded from masterplan roots (planner) — they're cross-cutting
referents, not planning roots. Exposed as the `extract_entities(note_id)` agent-write tool (reads the
verbatim original + current title/body). **Deferred:** an LLM entity-extractor adapter (heuristic
fallback); auto-extraction in the `organize` pipeline.

## Next (step) — a second Renderer / `LlmEntityExtractor` (ROADMAP items 5 / 3-followup)
