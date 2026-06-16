# 4. Planning model: one graph, plans as projections

- **Status:** Accepted
- **Date:** 2026-06-15

## Context

grandplan must turn a continuously-growing, overlapping, multi-horizon, *evolving* set of notes —
involving people, deadlines, and strict requirements — into actionable steps → plans → a life-spanning
masterplan. We need a model that handles all of this without becoming stale or a second jumbled mess.

## Decision

**One append-only knowledge graph; every plan (up to the masterplan) is a deterministic projection of it.**

- **Horizons:** each node has `horizon` ∈ {Masterplan, Goal, Project, Next-Action} (GTD Horizons / OKRs);
  the masterplan is the top of the `part_of` hierarchy.
- **Typed edges** capture structure: `depends_on`, `blocks`, `next`, `part_of`, `waiting_on`, `involves`,
  `builds_on`, `refines`, `supersedes`, `contradicts`, `relates`.
- **People/entities** are first-class nodes (`type: entity`); `waiting_on`/`involves` model delegation
  and stakeholders.
- **Deadlines/requirements:** `due` + `requirements[]`; scheduling propagates along the dependency DAG.
- **"Do together":** tasks with no dependency edge that share a `context`/resource/entity form a
  **parallel batch** (Critical-Path Method + GTD contexts).
- **Daily stream:** capture → inbox → triage → review loop keeps intake frictionless and processed.
- **Projections (the `Planner`):** hierarchy (`part_of`), sequence (topo-sort of `depends_on`), parallel
  batches, a "now" list (unblocked actions), and — later — critical path. Plans are recomputed, never
  hand-maintained, so they are never stale.

Borrows from GTD (Horizons, contexts, waiting-for, weekly review), OKRs, PARA, Zettelkasten,
Critical-Path Method, and Hierarchical Task Networks.

## Consequences

- The masterplan is just the top of a projection — always consistent with the graph.
- **MVP slice:** schema + `Planner` doing hierarchy + a "now" list. **Deferred:** critical-path
  scheduling, parallel-batch detection, OKR roll-ups, automated review (additive — no re-modeling).
- See ADR-0005 for workspaces, capability plugins, and multi-medium renderers built on this model.
