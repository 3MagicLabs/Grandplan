# SPEC — P0 trio + Track-1 foundation (post-research adoption)

Source: `docs/research/LANDSCAPE.md`. All slices honor the non-negotiables (offline-only, lossless,
local LLM, 16GB no-GPU) and ship test-first with the borromeo gate green. One concern per slice.

## Slice 1 — Backlinks ("Linked mentions")  ✅ core-testable (WSL)
**Why:** every PKM tool surfaces inbound links; near-free from grandplan's existing edges; portable
(written into the Markdown, not only Obsidian's pane). Extends the linking fix.
**Contract:** a rendered note gains a `## Linked mentions` section listing each note that links *to* it,
as `- <kind> [[<source-filename>|<source-title>]]` — by filename (never id), resolved via the same
per-projection `stems` map. Section is managed (regenerated; never clobbers the body). Empty → omitted.
**Edges:** `## Linked mentions` added to `_MANAGED_HEADINGS`; rendered after `## Links`, before
`## Resources`. A backlink whose source note is unknown is dropped (no phantom).
**Files:** `core/vault.py` (`_backlinks`, render), `core/project.py` (`write_notes` builds inbound map),
`core/ports.py` (writer signature), tests.

## Slice 2 — Chunk/block-level embeddings  ✅ core-testable (WSL)
**Why:** grandplan is alone at note-level; this is the precondition for hybrid retrieval & sharper
linking (LANDSCAPE Track 1). Keystone refs (MIT/Apache): Haystack/llmware splitters; LightRAG.
**Contract:** a pure `core/chunk.py` splits a note body into overlapping chunks (paragraph-aware,
bounded size); a `ChunkEmbedder`/index maps note_id → list[(chunk_text, vector)]; similarity can match
at chunk granularity and roll up to the owning note (max-pool). Fully offline (reuses `Embedder` port).
Backwards compatible: note-level path keeps working; chunking is additive.
**Files:** `core/chunk.py` (new, pure), tests. Wiring into reconcile/repository is a later slice.

## Slice 3 — Related-notes-at-review + one-click link  ⚠ core logic only (Qt GUI deferred to Windows)
**Why:** P0; reinforces the "connected vault" promise; reuses the embedder.
**Contract (core):** a pure function returns top-k related existing notes for a proposed note
(`most_similar` over the embedder) with scores, as approve-time link candidates. The Qt review-panel
binding + one-click `[[link]]` insertion is a Windows adapter (deferred; can't run Qt under WSL).
**Files:** `core/*` (selection logic + tests now); `app/`/`adapters/` GUI later.

## Slice 4 — Quick-capture box  ⚠ core logic only (Qt GUI deferred to Windows)
**Why:** P0; biggest capture-UX gap (Memos). LOW effort once the popup exists.
**Contract (core):** typed text → existing `CaptureCoordinator.submit()` path (no text-selection
prerequisite). Core already supports arbitrary text; the new surface is a Qt popup (Windows adapter,
deferred). Verify the core entry accepts typed input via a test.

## Deferred / flagged
- **Placeholder nodes (Foam):** needs an *edge-to-named-concept* model (link to a not-yet-existing note
  by name). grandplan edges are id-to-id between existing notes; adding naive placeholders would
  reintroduce id-named phantoms (the bug just fixed). Requires a named-target edge model — separate slice.
