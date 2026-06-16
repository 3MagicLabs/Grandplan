# 2. Obsidian vault is the storage + visualization layer

- **Status:** Accepted
- **Date:** 2026-06-15
- **Supersedes:** earlier exploration of a custom PySide6 graph UI (see RESEARCH.md §0.1)

## Context

We need a clean, semantically meaningful visualization — not a second jumbled pile of notes.
Building a custom graph viewer is large and risks being a worse Obsidian. The user already uses
Obsidian and is "headed there." Obsidian is local-first, offline, plain-Markdown, has a mature
graph view, and a plugin ecosystem.

## Decision

grandplan **writes clean, atomic, well-linked Markdown into an Obsidian vault**; Obsidian provides
the graph and navigation. We do **not** build a custom graph UI. grandplan stays an external
**Python** capture/organizer app that writes *into* the vault — **not** an Obsidian (TypeScript)
plugin (a plugin couldn't capture from any app and would break the Python quality gate). The vault
is the user-facing source of truth; an internal SQLite index (embeddings, edges) is derived from it.

## Consequences

- We focus effort on the novel parts: system-wide capture, losslessness, organization, linking, dedup.
- Plain `.md` files = portable, reusable by future software; **low lock-in** (files survive without Obsidian).
- "Clean, not jumbled" is *our* responsibility via atomic notes, consistent schema, semantic linking,
  and **dedup/merge before create** — Obsidian alone does not guarantee it.
