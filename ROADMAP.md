# grandplan — Roadmap & Vision

> Durable capture of where the platform is going (state lives in the repo, not chat). Authoritative
> for sequencing; defers to `SPEC.md` for MVP contracts and `FINDINGS.md` for the quality diagnosis.
> **Date:** 2026-06-18.

## North star

An **offline-first, agent-operable knowledge platform**: capture anything → organize it into one
append-only knowledge graph → project it into plans, deliverables, and integrations → let AI agents
(and eventually collaborators) read, distill, enrich, and extend it — **without ever breaking
offline-by-default (QAS-1) or lossless/append-only (QAS-2)**.

## Done

- **MVP** (capture → organize → review → vault + links + dedup → plan/graph projections), offline & gated.
- **"Git for ideas" substrate (PR-A…PR-E)** — event-sourced status/edits/history/resources + `attach`.
- **PR-F trustworthy organization** — LLM default + fail-loud; QAS-8 quality checks; diagnostic
  report; `regenerate` + `doctor`.
- **PR-G relational organization (keystone)** — structural `part_of`/`depends_on` placement → real
  hierarchy + dependency sequence (CLI + GUI).

## Non-negotiable invariants (apply to everything below)

- **Offline by default (QAS-1):** zero non-localhost egress in the core; `test_offline.py` guards it.
  Networked features live in a separate, opt-in, off-by-default connector layer.
- **Lossless / append-only (QAS-2):** every change — including agent and collaborator changes — is an
  *event*; originals are never mutated; current state is *derived*.
- **Ports & adapters (ADR-0003):** new capabilities enter behind ports; the core stays platform-agnostic.

## Themes (capabilities left to build)

### A. Agent-operable vault (HIGHEST LEVERAGE — unifies most of the vision)
A programmatic, append-only API + a **local MCP server** so AI agents (Claude Desktop, local agents)
can over stdio: **query** (notes/edges/plan/masterplan/search), **distill/extract** (summaries,
entities, structured slices), **enrich** (add tags/properties/metadata, place edges, set status),
**create** (propose notes/edges as events), and **generate** (render deliverables). All writes go
through the existing event operations (`record_edit`/`set_status`/`add_edge`/`add_resource`/placement),
so agent modification is safe, reversible, and offline. Subsumes the "other AIs" integration.

### B. Integrations / connectors (`Connector` port)
- **Local (offline, default-safe):** ✅ **`.ics` calendar export DONE** (`grandplan calendar`).
  ✅ **Productivity exports DONE** (`core/export.py` `to_markdown_tasks`/`to_csv`; `grandplan export
  --format tasks|csv` — Obsidian-Tasks/GitHub checklist + spreadsheet CSV, zero egress). ✅ MCP
  server (theme A) DONE. Remaining local: Todoist-import format.
- **Networked (opt-in, off by default, egress-flagged):** live Google Calendar 2-way sync; cloud-AI
  bridge; Notion/Todoist live sync. Isolated adapters; core egress test still guards the offline path.

### C. Smarter organization (build on PR-G)
- ✅ **`blocks` / `waiting_on` edges + feasible `Timeline.md` DONE** (placement + planner +
  `get_timeline`). ✅ **Critical-path + parallel-batch scheduling DONE** (`core/schedule.py`
  `critical_path`/`parallel_batches` — pure DAG analytics over open tasks; surfaced in the report).
  ✅ **Entity extraction** (people/org `entity` nodes + `involves` edges) DONE. Remaining: `next`
  sequencing, OKR roll-ups.
- Contradiction-resolution UX (data exists; no UI). ✅ **RC5 slug-based linking DONE** — links render
  `[[<filename>|<title>]]` (the target's real slug, native Obsidian resolution, export-safe) via
  `plan_filenames`; broken links to unknown notes are skipped; empty `<id>.md` phantom stubs are swept.

### D. Workspaces & capability plugins (SPEC §11.3)
Focused subsets ("workspaces") with domain `Capability` modules: people-graph, company/org-graph,
image-network, records/table, timeline; optionally materialized as their own Obsidian vaults.

### E. Renderers / deliverables (SPEC §11.4)
Beyond Markdown/JSON/Plan/Masterplan: documents/reports, slides/PPTX, and other mediums — each a
`Renderer` behind the port. (Ties to theme A: agents "generate things".)

### F. Navigable / interactive graphs
Richer Obsidian graph (more metadata, colors, saved filters/queries) now; a custom interactive graph
view later (note: a custom graph UI was an MVP non-goal — revisit deliberately).

### G. Cross-vault & collaborative (bigger; concurrency + trust)
- **Cross-vault:** operate over multiple vaults; move/merge/link notes across them; the API/MCP target
  any vault path. (SPEC §11.6 multiple/materialized vaults.)
- **Collaborative (multi-user):** currently a hard non-goal (§5). Needs a concurrency/merge model
  (the append-only event log is a strong foundation — CRDT/event-merge) + a trust/permission boundary.

### H. Capture surfaces
✅ **Voice/STT capture seam DONE** ("PR-H") — `adapters/voice.py` `VoiceCapturer` (conforms to the
`Capturer` port) with an injected `Transcriber` (logic gated offline); the real backend is a local
Whisper model + mic (`grandplan[voice]`, lazy/optional, on-device — no audio leaves the machine).
**Deferred:** GUI wiring (a "hold to speak" hotkey on the tray app — Windows-only, untestable under
WSL). Remaining surfaces: image/screenshot OCR; web clipper; social/feed ingestion; file/folder watch.

### I. Distribution & robustness
Windows packaging (PyInstaller/Briefcase + bundled model); model/quantization benchmark on the user's
CPU; `regenerate` history-preservation option.

### J. Agent intake — directives + playbooks (the "send to my agent and act" loop)
✅ **Offline spine DONE** (`core/directive.py`; `SPEC-AGENT-INTAKE.md`). Send content + an instruction
(ad-hoc or a named **playbook** like `profile-and-connect`) → an append-only `Directive` an agent
pulls over MCP (`grandplan mcp --directives` → `list_directives`/`complete_directive`) and fulfils
with the existing write/search tools. `grandplan directive add|list`. This is the in-house analogue of
openclaw / Claude Cowork, but running against our append-only graph with our invariants.
✅ **Phone→agent transport DONE** (chosen: local HTTP) — `adapters/http_intake.py` +
`grandplan serve`; `POST /directive`, binds 127.0.0.1 by default, refuses a routable host without a
`--token` (constant-time bearer check). A phone shortcut POSTs content+playbook over the LAN/VPN.
**Deferred (still the user's decisions):** (a) **live web research** — chosen *fully offline for now*;
a networked, opt-in `Researcher` port remains the future path; (b) an **auto-run daemon** that
dispatches pending directives to a local agent.

## Recommended sequence (highest leverage first, each offline-safe & spec-aligned)

1. ✅ **Agent-operable vault read API + local MCP server DONE** (`core/query.py` `VaultQuery` +
   `TOOLS`/`dispatch`; `adapters/mcp_server.py` stdio; `grandplan mcp`). Agents query/search/distill
   notes, plan, masterplan, graph, doctor — offline. `SPEC-AGENT-VAULT.md`.
2. ✅ **Agent write operations over the event log DONE** (`core/write.py` `VaultWrite` +
   `WRITE_TOOLS`/`dispatch_write`; `adapters/mcp_server.py` `tools_for`/`route`; `grandplan mcp
   --write`). Agents enrich/organize/create safely — `set_status`/`record_edit`/`add_resource`/
   `place`/`propose_note`, each an append-only event reusing PR-A…PR-G ops, validated + idempotent,
   read-only by default. The literal "agents improve/modify/distill/extract/add/organize/generate"
   ask. `SPEC-AGENT-VAULT.md` §"Step 2".
3. ✅ **Entity extraction + `involves` edges DONE** (`core/entities.py` `EntityExtractor` port +
   `HeuristicEntityExtractor` + `materialize_entities`; exposed as the `extract_entities` agent-write
   tool). People/org mentions become `entity` nodes joined by `involves` edges, so the graph is a
   people/org graph agents can reason over. Append-only + idempotent; entity ids content-addressed by
   name (dedupe); `entity` nodes excluded from masterplan roots. `LlmEntityExtractor` adapter
   (`adapters/llm_entity_extractor.py`, Ollama-backed, unioned with the heuristic + fallback) and
   **auto-extraction wired into `organize`/`regenerate`** (LLM default, `--no-llm` → heuristic) — so
   entities appear automatically, not only via the agent tool.
4. **`.ics` calendar export (theme B, local).** First connector; offline; builds on planner/horizons.
5. ✅ **A second Renderer DONE** (`core/render.py` `Renderer` port + `MarkdownReportRenderer`;
   `grandplan report -o <vault> [--out PATH] [--title T]`). Composes plan + masterplan + timeline +
   health into one self-contained Markdown **deliverable** (summary, top priorities, blocked,
   schedule, hierarchy by horizon, open questions, graph health) — offline, deterministic, pure.
   Proves "knowledge → deliverable". **Deferred:** a slides/PPTX renderer; agent `render` write tool.

Then, behind explicit decisions: networked connectors (B), workspaces/capabilities (D), interactive
graph (F), and the big one — cross-vault → collaboration (G).

## Open decisions (the user's to make, when we reach them)

- **Networked-connector boundary** — local-first only, vs. local-first + opt-in networked, vs.
  cloud-sync-first (relaxes the offline promise). *Leaning: local-first + opt-in networked.*
- **Collaboration model** — event-merge/CRDT over the append-only log; trust/permission boundary.
- **Interactive graph** — enrich Obsidian (cheap) vs. build a custom UI (big; was a non-goal).
