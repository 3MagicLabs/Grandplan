# 5. Workspaces, capability plugins, and multi-medium renderers

- **Status:** Accepted
- **Date:** 2026-06-15
- **Builds on:** ADR-0004 (planning model), ADR-0002 (Obsidian vault), ADR-0003 (ports & adapters)

## Context

Notes shouldn't all live in one undifferentiated vault. The user needs to focus a subset, organize and
analyze it its own way (people graphs, company graphs, image networks, records, misc.), and turn groups
of notes into deliverables (a presentation/PowerPoint, documents, other frameworks). New notes that
relate to an existing thread must be reconciled (build-on / refine / supersede / contradict) so the
knowledge base stays consistent.

## Decision

Three extension points on the one-graph model (ADR-0004), all using the **Strategy / plugin** pattern
behind ports so the core never changes when capabilities are added:

1. **Reconciler** — on capture, classify a note vs nearest existing notes and maintain consistency
   append-only: `duplicate`→merge, `builds_on`/`refines`→link/update, `supersedes`→supersede (old kept),
   `contradicts`→**flag `needs-review` (never auto-resolve)**. LLM-proposed, human-approved.
2. **Workspaces/Collections** — a named subset of notes (membership/query) with enabled **Capability
   modules** (`people-graph`, `org-graph`, `image-network`, `records`, `timeline`, …) behind a
   `Capability` port. A workspace is a virtual view or is **materialized as its own Obsidian vault**.
3. **Renderers** — the `Planner` generalizes to a family of `Renderer`s: graph-subset (+ template) →
   medium. Built-in: Markdown, JSON graph, `Plan.md`. Later adapters: PPTX/slides, documents, etc.

## Consequences

- Adding a domain capability, a vault, or an output medium is an **additive adapter/plugin** — no core
  change (CS130 information hiding / low coupling; open–closed).
- **MVP slice:** single default vault; Reconciler (duplicate/build-on/supersede/contradict-flag);
  Renderers = Markdown + JSON + basic `Plan.md`. **Deferred:** multiple/materialized vaults, domain
  Capability plugins, PPTX/other-medium renderers.
- **Risk:** capability sprawl can balloon scope — each capability is gated behind its own phase/issue and
  must justify itself; the thin capture→organize→note→vault loop ships first.
