# 8. "Git for ideas": event-sourced progress + embedded resources

- **Status:** Proposed
- **Date:** 2026-06-17

## Context

Two user goals that are really one:
1. **Realize progress.** As work advances, the user must update existing notes' status/details so the
   plan reflects reality ("done: built the resume", "launch slipped to Q3") — "a **git for ideas and
   plans**".
2. **Attach real artifacts & references.** Notes describe websites, GitHub repos, PDFs, docs, images.
   These should appear in the note as **links/embeds (or placeholders)**, and the user should be able
   to hand an agent a *newly-created* artifact ("here's the doc that note X asked for") and have it
   **parse the vault, attach it to the right note(s), mark progress, and update related notes.**

Both are the same operation: **new input → match the relevant existing note(s) → record an update →
re-project** — without ever mutating or losing the original (lossless/append-only, QAS-2).

grandplan is already git-shaped: `index.jsonl` is an append-only event log, notes are
content-addressed and immutable, and `Plan.md`/`graph.json` are derived projections. What's missing
is the **"commit a change"** verb.

## Decision

Make the index a true **event log** and derive current state from it ("git for ideas"):

- **New event kinds appended to `index.jsonl`** (alongside today's `note`/`edge`): `status`
  (note → new status), `edit` (note → field changes: body/title/tags/due), `resource` (note →
  attached link/path/image, or a *placeholder* expectation), `link` (already an edge). Every event
  carries a timestamp. **Nothing is mutated**; the note/original records stay byte-exact.
- **Current state is derived** — the repository gains `status_of(note_id)`, `resources_of(note_id)`,
  `history_of(note_id)` (= the note's commit log). The Planner reads `repo.status_of(...)` instead of
  the note's creation status; `done` leaves "Now" and unblocks dependents; `Plan.md` shows progress.
- **Capture/agent-driven update flow** (reuses the dedup/reconcile + review machinery): new input
  (a text update *or* an artifact path/URL) → embed → **match the relevant note(s)** by similarity +
  LLM confirmation → propose the change (status / attach-resource / edit / link) → **human approves in
  the review dialog** → append the event → re-project. Matches the user's "say an update later, it
  updates the relevant tasks/plans."
- **Resources render natively in Obsidian:** frontmatter `resources:` / `links:` + inline
  `[label](url)`, `[[file]]`, `![[image]]`; an unfulfilled expectation ("make a doc that does X")
  renders as a **placeholder** the attach-flow later fills.
- **Voice** is a future capture source feeding the same flow (currently a SPEC non-goal).

## Phased plan (each a gated, reviewed PR)

- **PR-A — event substrate:** `status` events in the log + `repo.status_of` + Planner derives current
  status (done→unblocks/leaves Now) + vault frontmatter writes current status. *Foundation.*
- **PR-B — capture-driven status updates:** detect update-intent on capture, match the note, propose a
  status change in the review dialog, append on approve.
- **PR-C — detail edits + history:** `edit` events; per-note history ("git log") surfaced; a
  "what moved" progress digest section in `Plan.md`.
- **PR-D — resource references (schema + render):** `resource`/`link` fields; render Obsidian
  links/embeds/placeholders; organizer extracts URLs/paths from captures.
- **PR-E — artifact-attach flow:** `grandplan attach <path|url>` (and capture-driven) → parse the
  vault, semantic-match the fulfilled note(s), attach the resource, mark progress, propagate to
  related notes. ("Here's the doc for note X → update my vault.")
- **PR-F (later) — voice capture** behind the `Capturer` port (offline STT).

## Consequences

- **Lossless/append-only preserved**: progress and attachments are *events*, never mutations; full
  history per note (the "git log for an idea"). Offline throughout.
- The Planner/vault/graph become projections of the event log — consistent with ADR-0004/0007.
- Each PR is independently shippable and gated; the substrate (PR-A) unblocks the rest.
