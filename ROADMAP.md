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
- **Local (offline, default-safe):** ✅ **`.ics` calendar export DONE** (`grandplan calendar`,
  `core/calendar.py` — dated notes → subscribe-able feed, zero egress); productivity exports
  (Todoist-import / Markdown-Tasks / CSV) and the MCP server (theme A) remain.
- **Networked (opt-in, off by default, egress-flagged):** live Google Calendar 2-way sync; cloud-AI
  bridge; Notion/Todoist live sync. Isolated adapters; core egress test still guards the offline path.

### C. Smarter organization (build on PR-G)
- `blocks` / `next` / `waiting_on` edges; critical-path scheduling; parallel-batch detection; OKR
  roll-ups. **Entity extraction** (people/org `entity` nodes + `involves` edges) — seeds intelligence use-cases.
- Contradiction-resolution UX (data exists; no UI). RC5 robust slug-based linking (kill phantom-id nodes).

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
Voice/STT (next per HANDOFF, "PR-H"); image/screenshot OCR; web clipper; social/feed ingestion; file/folder watch.

### I. Distribution & robustness
Windows packaging (PyInstaller/Briefcase + bundled model); model/quantization benchmark on the user's
CPU; `regenerate` history-preservation option.

## Recommended sequence (highest leverage first, each offline-safe & spec-aligned)

1. **Agent-operable vault read API + local MCP server (theme A, read-only first).** Lets agents query
   notes/graph/plan/search. Offline, immediately useful, foundation for everything.
2. **Agent write operations over the event log (theme A, append-only).** Agents enrich/organize/create
   safely. This is the literal "agents improve/modify/distill/extract/add/organize/generate" ask.
3. **Entity extraction + `involves` edges (theme C).** Turns notes into a people/org graph — seeds the
   intelligence use-cases and gives agents richer structure to operate on.
4. **`.ics` calendar export (theme B, local).** First connector; offline; builds on planner/horizons.
5. **A second Renderer — document or slides (theme E).** Proves "knowledge → deliverable" + agent generation.

Then, behind explicit decisions: networked connectors (B), workspaces/capabilities (D), interactive
graph (F), and the big one — cross-vault → collaboration (G).

## Open decisions (the user's to make, when we reach them)

- **Networked-connector boundary** — local-first only, vs. local-first + opt-in networked, vs.
  cloud-sync-first (relaxes the offline promise). *Leaning: local-first + opt-in networked.*
- **Collaboration model** — event-merge/CRDT over the append-only log; trust/permission boundary.
- **Interactive graph** — enrich Obsidian (cheap) vs. build a custom UI (big; was a non-goal).
