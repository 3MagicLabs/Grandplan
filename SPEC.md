# grandplan — MVP Specification

> Requirements written with CS130 discipline: functional needs as **user stories** (INVEST)
> with **Given/When/Then** acceptance criteria; non-functional needs as **measurable QAS**;
> explicit **non-goals**; key **contracts** + **delayed decisions**. The "how" (libraries,
> models) lives in `RESEARCH.md`; this doc is mostly the **what**. Authoritative for the MVP.
>
> **Date:** 2026-06-15 · **Status:** draft for review · supersedes ad-hoc notes above it.

## 1. Context & Scope

The user's knowledge is scattered across many apps and formats. grandplan is a **native
Windows, fully-offline desktop app** that lets the user **select text in any app**, capture it
with a **global hotkey**, have a **small local LLM** organize it into a **clean, atomic note**,
**approve** it, and write it as **well-linked, de-duplicated Markdown into an Obsidian vault**.
Obsidian is the viewer/graph. The vault is plain Markdown (portable, reusable by future
software). The long-term aim: fold notes, ideas, references (later: voice, images, social
graphs) into one **actionable, organized plan** — where the plan is a *projection* of the graph.

**Primary actor:** the User (a single person, on their own machine).
**Out-of-band dependency:** Obsidian (free, local) renders the vault; grandplan writes files into it.

## 2. Glossary (shared vocabulary)

- **Selection** — text the user highlights in any application.
- **Capture** — the act of grabbing the current selection (global hotkey → clipboard/UIA).
- **Original** — the selection stored **verbatim**, never mutated (the lossless anchor).
- **Note** — an atomic Markdown file in the vault: frontmatter + organized body + the Original.
- **Vault** — the user's Obsidian folder of `.md` files + `[[wikilinks]]` (source of truth).
- **Index** — internal SQLite store (embeddings, provenance, edges) derived from the vault.
- **Plan** — a generated Map-of-Content projecting the graph's actionable structure.

## 3. Goals — Functional requirements (user stories + acceptance criteria)

> Each story references an ID for traceability (commits/PRs cite `US-n`). All pass INVEST
> (notes added where a dependency or split is relevant).

### US-1 — Capture a selection from any app
*As a user, I want to select text in any application and capture it with a global hotkey, so
that I can collect information without switching tools.*
```
Given any application has text selected and grandplan is running,
When  I press the capture hotkey,
Then  the selected text is captured and the review panel opens with it.
```
```
Given the clipboard had prior contents,
When  capture simulates copy to read the selection,
Then  my prior clipboard contents are restored afterward.
```
*INVEST: independent; testable. (Capture mechanism = design decision, see RESEARCH §2a.)*

### US-2 — Never lose or distort the original (LOSSLESS — top priority)
*As a user, I want my original captured text preserved exactly, so that organization can never
corrupt or lose what I actually wrote.*
```
Given a selection of arbitrary text (unicode, emoji, code, whitespace),
When  it is captured and later organized and stored,
Then  the exact original characters are retrievable verbatim, byte-for-byte, unchanged.
```
```
Given a stored note,
When  I inspect it,
Then  the Original is present in full and visibly distinct from the organized/derived content.
```
*INVEST: valuable, testable. This is the first thing built and tested (TDD).*

### US-3 — Organize a capture into a clean atomic note (offline LLM)
*As a user, I want the captured text turned into a clean, self-contained note, so that it's
understandable later without the surrounding noise.*
```
Given a captured selection,
When  I trigger organize,
Then  a local model proposes a note: a concise title, a cleaned/structured body, suggested
      type and tags — produced fully offline — while keeping the Original intact (US-2).
```
```
Given the model returns malformed structured output,
When  the result is validated against the note schema,
Then  the system repairs/retries and never writes an invalid note.
```
*INVEST: negotiable (model is a design choice); testable via a fake Organizer.*

### US-4 — Review and approve before anything is written
*As a user, I want to review (and edit) the proposed note and approve it, so that nothing junk
ever lands in my vault.*
```
Given a proposed note,
When  I edit fields and click Approve,
Then  the note is written to the vault with my edits.
```
```
Given a proposed note,
When  I click Discard,
Then  nothing is written to the vault or the index.
```

### US-5 — Link the note to semantically related notes
*As a user, I want a new note automatically linked to related existing notes, so that my
knowledge connects instead of piling up in isolation.*
```
Given existing notes in the vault and a new approved note,
When  it is written,
Then  it contains `[[wikilinks]]` to the most semantically related existing notes (above a
      similarity threshold), and those targets are real notes (no broken links).
```

### US-6 — De-duplicate / merge instead of creating a second mess
*As a user, I want near-duplicate captures to merge or link, so that my vault never becomes a
second jumbled pile of redundant notes.*
```
Given a capture highly similar to an existing note (above a merge threshold),
When  I organize it,
Then  the system proposes merging into / linking the existing note rather than creating a new
      one, and I can choose merge, link, or create-new.
```
*INVEST: depends on US-5 (embeddings). The single most important anti-mess rule.*

### US-7 — Write a clean Markdown note into the Obsidian vault
*As a user, I want approved notes saved as clean Markdown in my vault, so that Obsidian shows
them in the graph and I own portable files.*
```
Given an approved note,
When  it is written,
Then  a `.md` file appears in the vault with consistent frontmatter (id, type, created, source,
      tags, status) + body + Original block, and is valid for Obsidian (renders, graph-links work).
```

### US-8 — Plan-ready structure → generate an actionable plan (projection)
*As a user, I want my notes to carry actionable structure and to generate an ordered plan, so
that my knowledge becomes an executable grand plan.* (Schema: Phase 0; generator: later phase.)
```
Given notes typed as task/project/goal with status/priority/due and dependency edges,
When  I generate the plan,
Then  grandplan writes a plain-Markdown `Plan.md` MOC listing actionable items grouped by
      project/goal and ordered by the dependency DAG (topological) + priority/due — derived
      purely from the graph (no hand-maintenance), and re-generating reflects the current graph.
```
*INVEST: negotiable; valuable. Plan = projection of the graph (one source, three views).*

### US-9 — Portable export for future software
*As a user, I want my data in open formats, so that software I build later can consume it.*
```
Given a vault of notes,
When  I export,
Then  I get plain Markdown notes + a JSON graph (nodes + typed edges) with no proprietary lock-in.
```

## 4. Goals — Non-functional requirements (Quality Attribute Scenarios)

> Stimulus + **measurable** Response Measure. Numbers marked *(target — benchmark in Phase 0)*
> are provisional until measured on the user's hardware.

- **QAS-1 Offline (hard).** *Stimulus:* any operation, including embedding + LLM inference.
  *Response:* **zero network egress to non-localhost**; the full pipeline completes with the
  network interface disabled; an automated egress check asserts no non-loopback sockets.
- **QAS-2 Lossless (hard).** *Stimulus:* capture + organize + store any of a corpus of adversarial
  inputs (unicode/emoji/code/long/whitespace). *Response:* **100% byte-exact** recovery of every
  Original; **0** modifications. Property-based round-trip test in the gated core.
- **QAS-3 Latency.** *Stimulus:* user organizes a typical selection (≤2 KB). *Response:* proposed
  note shown in **≤10 s** *(target)* on the modest target CPU; capture itself (hotkey→panel) in **≤1 s**.
- **QAS-4 Modest hardware.** *Stimulus:* app running with a small model + embeddings.
  *Response:* fits within a **16 GB-RAM** machine with no dedicated GPU *(target; model ≤ ~4–6 GB q4)*.
- **QAS-5 Maintainability.** *Stimulus:* swap the LLM runtime or the vector store. *Response:*
  achievable in **≤1 developer-day** with **no change to the core** (everything behind ports).
- **QAS-6 Privacy/Safety.** *Stimulus:* normal use. *Response:* no secrets stored; vault stays
  local; the user's pre-existing clipboard is preserved (US-1); no telemetry.
- **QAS-7 Coherence (anti-mess).** *Stimulus:* capturing many overlapping items over time.
  *Response:* duplicate rate stays low — every new note either links to ≥1 related note or is an
  intentional root; near-duplicates trigger the merge path (US-6).

## 5. Non-Goals (explicitly out of scope for the MVP)

- Social-media auto-capture; Instagram/LinkedIn ingestion; LinkedIn connections/job analyzer.
- Voice-to-text; image capture/OCR (we capture *selected text*, not pixels).
- Cross-device sync (vault sync is the user's choice, e.g. existing tools).
- A **custom graph UI** — Obsidian is the viewer.
- Bulk/automatic processing without human approval.
- Multi-user / collaboration / cloud anything.

## 6. The Design (high level — contracts & structure; details in RESEARCH.md)

### 6a. Ports & adapters (CS130 information-hiding / design-for-change)
Platform-agnostic **core** (borromeo-gated, TDD in WSL2) depends only on **ports**:
- `Capturer` — get current selection (Windows adapter: hotkey + clipboard/UIA).
- `Organizer` — text → proposed note (Windows adapter: Ollama/llama.cpp; fake for tests).
- `Embedder` — text → vector (adapter: local sentence-transformer; fake for tests).
- `Repository` — persist/query Index (adapter: SQLite + sqlite-vec).
- `VaultWriter` — write/read Markdown notes (adapter: filesystem Obsidian vault).
- `Planner` — project graph → `Plan.md` (pure core logic; topological sort of dependency DAG).

### 6b. Pipeline
`capture → preserve Original (lossless) → organize (LLM, validated) → embed → find related +
dedup check → human review/approve → write note (+ links) to vault → update Index`. Plan
generation is a separate, on-demand projection over the Index/vault.

### 6c. Note schema (the plan-ready contract)
Frontmatter (every note): `id`, `type` (idea|reference|task|project|goal|decision|question),
`created`, `source` (app/title/url if any), `tags[]`, `status` (inbox|next|active|done),
`priority?`, `effort?`, `due?`, `project?`, `links` (typed: `depends_on|blocks|next|part_of|supports|relates → [[ids]]`).
Body: organized content + `- [ ]` action items where applicable. **`## Source (original)`** block:
the Original verbatim (lossless). Typed dependency edges form the DAG the Planner sorts.

### 6d. Lossless contract (the core invariant)
For every note: `original_text` is stored verbatim and is reconstructable byte-for-byte; no
pipeline stage may mutate it; the organized body is *derived* and always separable from it.
Verified by QAS-2's property-based round-trip test — built and passing **before** any LLM work.

## 7. Acceptance test (MVP definition of done)

Select text in Notepad (or any Windows app) → hotkey → a clean note is proposed → approve →
a Markdown note appears in the Obsidian vault, **linked** to related notes, with the **Original
preserved verbatim**; a near-duplicate capture offers **merge**; running plan-generation
produces a `Plan.md` ordered by dependencies; data exports as Markdown + JSON graph; the whole
flow runs with **networking disabled**.

## 8. Delayed decisions (track until resolved — CS130 "delay & track")

- LLM runtime: **Ollama** (easy, external) vs **embedded llama-cpp-python** (self-contained) — decide at Phase 3 (packaging needs).
- Exact local model + quantization — decide after a Phase-0/3 quality+latency benchmark on the user's CPU.
- Plan rendering: self-generated `Plan.md` only vs also leveraging Obsidian Dataview/Tasks/Bases — keep self-generated as the no-lock-in baseline.
- Capture coverage: clipboard (universal) vs UIA (cleaner) per target app — measure on real apps in Phase 1.
- Windows packaging/distribution (PyInstaller/Briefcase + bundling the model) — Phase 4.

## 9. Key edge cases (must be handled)

- Empty/whitespace-only selection → no-op with a clear message.
- Huge selection (e.g. >100 KB) → still lossless; organize may chunk; latency budget relaxes.
- Non-text/binary on clipboard → reject gracefully, restore clipboard.
- LLM unavailable/timeout → keep the Original captured; allow "save raw, organize later."
- Vault path missing/locked, or filename collision → safe, non-destructive handling.
- Unicode/emoji/RTL/code blocks → preserved exactly (QAS-2 corpus).
- Near-duplicate ambiguity → user chooses merge/link/new (US-6).

## 10. Alternatives considered
See `RESEARCH.md` (web UI vs native; custom graph vs Obsidian; embeddings-only vs hybrid LLM;
sqlite-vec vs faiss/chroma) — each with the rationale for the choice made here.

## 11. Planning model, knowledge evolution & extensibility

**Unifying principle:** *one append-only knowledge graph; every output — notes, plans, the masterplan,
domain analyses, presentations — is a deterministic **projection** over a selected subset.* Inputs flow
through a **Reconciler** that maintains consistency without ever destroying an original.

### 11.1 Horizons (long ↔ short term)
Each node has a `horizon`: **Masterplan → Goal → Project → Next-Action** (GTD Horizons / OKRs). The
masterplan is the top of the projection hierarchy (`part_of` edges), recomputed as the graph changes.

### 11.2 Knowledge evolution & consistency — US-10
*As a user, I want a new note related to an existing thread reconciled with it — building on, refining,
or flagging contradictions — so my knowledge stays consistent, not duplicated or stale.*
The Reconciler classifies a new note vs the most-similar existing note(s): `duplicate`→merge (US-6);
`builds_on`/`enhances`→link (+ optional append); `refines`/`supersedes`→new is current, old kept
(append-only) + `supersedes` edge; `contradicts`→**never auto-resolved**: keep both, add a `contradicts`
edge, set `status: needs-review`, surface in the review queue.
```
Given an existing organized thread and a new related note,
When  it is captured and classified,
Then  the system proposes the relationship (build-on / refine / supersede / contradict) and, on approval,
      links/updates accordingly while preserving every original verbatim.
```

### 11.3 Workspaces & pluggable capabilities — US-11
*As a user, I want to focus a subset of notes into its own organized space with capabilities suited to
its domain (people/company graphs, image networks, records, …), so different subjects are analyzed their
own way — not all forced into one undifferentiated vault.*
A **Workspace/Collection** = a named subset (membership/query) with its own organization + enabled
**Capability modules**; a note may belong to several. A workspace can be a **virtual view** or be
**materialized as its own Obsidian vault**. **Capability modules** are plugins behind a `Capability` port
(Strategy): `people-graph`, `org/company-graph`, `image-network`, `records/table`, `timeline`, … added
without core changes.
```
Given notes tagged into a workspace,
When  I focus that workspace,
Then  I see only its notes, organized with its enabled capabilities, optionally as its own vault.
```

### 11.4 Render to other mediums — US-12
*As a user, I want to turn a group of notes/subjects into other frameworks (a presentation/PowerPoint, a
document, …), so my knowledge becomes deliverables.*
The `Planner` generalizes to a family of **Renderers** (Strategy): graph-subset (+ template) → target
medium. Built-in: Markdown note, JSON graph, `Plan.md`/`Masterplan.md`. Later: PPTX/slides, documents,
etc. — each a Renderer behind a port; no core change to add one.
```
Given a selected workspace or query and a chosen template,
When  I render,
Then  grandplan produces the deliverable (e.g. a presentation) projected from those notes.
```

### 11.5 Schema additions (cheap, forward-safe — committed NOW)
So nothing above is precluded later, extend the model now (implementation phased):
- node: add `horizon`, `context[]`, `due`, `requirements[]`, `collections[]` (workspace membership),
  `status` (now incl. `needs-review`, `superseded`); node type `entity` (person/org) is first-class.
- edges: add `waiting_on`, `involves` (→ Entity), `builds_on`, `refines`, `supersedes`, `contradicts`,
  `part_of` (with existing `depends_on`/`blocks`/`next`/`relates`).

### 11.6 MVP slice vs deferred (scope discipline)
- **MVP now:** the schema above; Reconciler with **duplicate + build-on + supersede + contradict-flag**
  (LLM-proposed, human-approved); `Planner` = **hierarchy + a "now" list**; **single default vault**;
  Renderers = Markdown + JSON graph + basic `Plan.md`.
- **Deferred (phased, additive — no re-modeling):** multiple/materialized vaults; domain Capability
  plugins (people/company/image graphs, records); critical-path scheduling; parallel-batch detection;
  OKR roll-ups; PPTX/other-medium Renderers; automated review.
