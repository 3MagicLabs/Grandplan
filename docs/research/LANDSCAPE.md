# grandplan — competitive landscape & adoption roadmap (synthesis)

**Date:** 2026-06-19. **Scope:** what the successful open-source second-brain / local-AI / PKM / planning
projects do well, and exactly what grandplan should borrow — every item filtered through the
non-negotiables: **offline-only · lossless · local LLM · 16GB no-GPU**. grandplan is **MIT**, so code may
be copied only from **MIT/Apache/BSD** sources (with attribution); AGPL/GPL/source-available projects are
**ideas-only**.

> **2026 refresh:** see [`REFRESH-2026.md`](REFRESH-2026.md) for a 2025–2026 update — notably **Reor archived (Mar 2026)** vacating grandplan's closest niche, plus LightRAG-style local knowledge-graph retrieval and the small-model (Gemma 3 4B / Phi-4-mini) consensus for 16 GB CPU boxes.

This file is the index + decision layer. Full per-area detail (verified star counts, licenses, per-repo
techniques) lives in the source docs:

| Area | Doc | Repos |
|---|---|--:|
| Closest analogs, 4-dimension landscape + first proposals | [`PRIOR-ART-ADOPTION.md`](PRIOR-ART-ADOPTION.md) | 20 |
| Karpathy "LLM-Wiki" pattern + correct link modeling | [`LLM-WIKI-DEEPREAD.md`](LLM-WIKI-DEEPREAD.md) | 13 |
| A — Offline AI second brains / RAG-over-notes | [`A-offline-ai-second-brains.md`](A-offline-ai-second-brains.md) | 16 |
| B — Obsidian/Logseq/SiYuan/Foam AI plugins | [`B-obsidian-logseq-ai-plugins.md`](B-obsidian-logseq-ai-plugins.md) | 18 |
| C — Note-taking & capture apps | [`C-notetaking-capture-apps.md`](C-notetaking-capture-apps.md) | 18 |
| D — AI memory & knowledge graphs | [`D-ai-memory-knowledge-graphs.md`](D-ai-memory-knowledge-graphs.md) | 17 |
| E — Notes → action / planning | [`E-notes-to-action-planning.md`](E-notes-to-action-planning.md) | 18 |

**~120 projects surveyed, all star counts/licenses verified live via the GitHub API.**

---

## 1. The verdict in one paragraph

grandplan's **thesis and its edge model are sound** — lossless verbatim + event-sourcing + human-approval +
an actionable plan is rare, and the recent fix made its `[[filename|title]]` linking the canonical hybrid
(name-first with an id safety net; going fully id-first would break grep-able offline Markdown — confirmed
by the SiYuan export-failure precedent). The richest **planning/edge model** of any tool surveyed is already
grandplan's. The real gaps are concentrated in two places: **(1) the retrieval/graph engine** — grandplan
embeds at *note* level and stuffs the *whole neighborhood* into the LLM, which will not scale; and **(2)
capture & day-to-day UX** — capture is text-selection-only, and there's no quick-capture, inbox, OCR,
dynamic queries, backlinks panel, or daily agenda.

## 2. Two strategic tracks

### Track 1 — The retrieval/graph engine (highest strategic value)
This is the "make the graph actually intelligent and scalable" track. Each step is a precondition for the
next, and **every keystone source is MIT/Apache (copyable)**.

1. **Chunk/block-level embeddings** — grandplan is *alone* at note-level. Low-risk precondition for
   everything below. *(splitters: Haystack/llmware/EmbedChain, all Apache/MIT.)*
2. **Hybrid retrieval (BM25 + dense) + local cross-encoder rerank + relevance-span extraction** — replaces
   "whole neighborhood → LLM" with "retrieve top-k across thousands of notes → rerank → feed only the
   relevant spans." Direct fix for the context bottleneck. *(kotaemon Apache; Langroid `DocChatAgent` MIT.)*
3. **Schema-guided entity/relation extraction → entities as first-class graph nodes** — turns unbounded
   neighborhood reconciliation into bounded per-chunk extraction. *(LlamaIndex `SchemaLLMPathExtractor` MIT;
   R2R's Triplex; LightRAG MIT.)*
4. **Incremental dedup/merge + edge-invalidation conflict resolution** — maps cleanly onto grandplan's
   event-sourced / tombstone substrate; lossless. *(graphiti, mem0 ADD/UPDATE/DELETE/NOOP, nano-graphrag.)*
5. **Graph-traversal retrieval without context-stuffing** — Personalized PageRank first; community/global
   summaries later for corpus-wide questions embeddings can't answer. *(fast-graphrag, nano-graphrag — MIT.)*

> **Keystone reference: [LightRAG (MIT)](https://github.com/HKUDS/LightRAG)** — entity/relation extraction +
> dual-level graph retrieval + incremental merge/delete, the single best-fit copyable engine. nano-graphrag
> (MIT) is the readable port. This is also the technique the LLM-Wiki deep-read flagged for *scaling to
> thousands of pages without a context bottleneck*.

### Track 2 — Capture & daily UX (highest near-term value-per-effort)
The "make it pleasant to live in every day" track. Mostly small, offline-safe.

- **Quick-capture box** — typed thoughts via a Qt popup → existing `CaptureCoordinator.submit()`. The single
  biggest UX gap; LOW effort. *(Memos MIT; org-capture pattern.)*
- **Inbox / capture-now-organize-later** — decouples capture from the synchronous local-LLM step (the exact
  coupling behind the ADR-0006 OOM cascade). Capture instantly; organize on demand/batched. *(org-capture
  refile; Logseq journals — pattern.)*
- **Related-notes panel at review + one-click `[[link]]`** — write-time embedding suggestions; reuses the
  embedder; reinforces the "connected vault" promise. *(Smart Connections, MIT-equivalent.)*
- **Backlinks ("Linked mentions") + placeholder nodes** — backlinks are near-free from existing edges; Foam
  *embraces* unresolved links as placeholder nodes — and "a placeholder set is literally what the plan still
  needs," a natural fit for grandplan's planner. *(Foam, MIT.)*
- **Offline OCR of images/PDFs** — Tesseract (lazy optional extra), CPU-only, fits 16GB. *(Joplin, verified
  offline OCR for images **and** PDFs.)*
- **Read-only query DSL + daily `Today.md` agenda** — Dataview/SilverBullet-SLIQ-style `filter/sort/group`
  over `VaultQuery`; "Today" = `due <= today AND not done` + calendar + recent captures. *(Dataview, SLIQ,
  org-mode, all MIT; Khoj automation loop as pattern.)*
- **Offline mention→wikilink densification** — auto-suggest links from existing note titles, no model call.
  *(automatic-linker, Apache.)*

## 3. Unified prioritized roadmap

Merges the PRIOR-ART-ADOPTION P-list with the A–E findings. All items are offline-safe.

| Pri | Item | Track | Source (license) | Value | Effort |
|---|---|---|---|---|---|
| **P0** | Quick-capture box | 2 | Memos (MIT) | ★★★ | Low |
| **P0** | Related-notes panel at review + one-click link | 2 | Smart Connections (MIT-eq) | ★★★ | Low |
| **P0** | Backlinks ("Linked mentions") + placeholder nodes | 2 | Foam (MIT) | ★★☆ | Low |
| **P1** | **Chunk-level embeddings** (engine precondition) | 1 | Haystack/llmware (Apache/MIT) | ★★★ | Med |
| **P1** | Hybrid retrieval + local rerank + span extraction | 1 | kotaemon (Apache) / Langroid (MIT) | ★★★ | Med |
| **P1** | Inbox / capture-now-organize-later | 2 | org-capture (pattern) | ★★★ | Med |
| **P1** | Daily `Today.md` agenda digest | 2 | org-mode/Khoj (MIT/pattern) | ★★★ | Med |
| **P1** | Read-only query DSL over VaultQuery | 2 | Dataview/SLIQ (MIT) | ★★☆ | Med |
| **P2** | Entity/relation extraction → entity nodes | 1 | LlamaIndex/LightRAG (MIT) | ★★★ | High |
| **P2** | Incremental dedup/merge + edge invalidation | 1 | graphiti/nano-graphrag (MIT) | ★★☆ | Med |
| **P2** | Graph-traversal (PPR) retrieval | 1 | fast-graphrag (MIT) | ★★☆ | Med |
| **P2** | Offline OCR (images + PDF) | 2 | Joplin/Tesseract (MIT) | ★★☆ | Med |
| **P2** | Taskwarrior urgency ranking for the "now" list | 2 | Taskwarrior (MIT) | ★★☆ | Low |
| **P2** | Scheduled-vs-deadline + recurrence | 2 | org-mode (MIT) | ★★☆ | Med |
| **P2** | Offline mention→wikilink densification | 2 | automatic-linker (Apache) | ★☆☆ | Low |

**Suggested sequence:** ship the **P0 trio** first (small, cohesive "frictionless capture + connected vault"
PR-set), then open the **engine track** with **P1 chunk embeddings → hybrid retrieval+rerank** (the highest
strategic lever, and the scaling fix), interleaving the P1 UX items (inbox, Today, query DSL) as cheap wins.

## 4. Constraint filter (rejected — do not adopt)

| Rejected | Seen in | Why |
|---|---|---|
| Cloud sync / hosted memory / account model | mem0 cloud, supermemory, Notesnook, Outline, Karakeep | network egress — offline-only |
| Default cloud LLM | AnythingLLM, Khoj, copilot | local-LLM non-negotiable |
| Heavy infra (Elasticsearch/Vespa/32B+ models) | some RAG stacks, cognee, Letta, R2R full | breaks 16GB no-GPU |
| Encrypted-blob storage (not plain Markdown) | Standard Notes, Notesnook | breaks grep-able lossless Markdown |
| Fully id-first linking | Logseq/SiYuan | breaks offline-Markdown portability (links die on export) |
| RSS auto-hoard / remote web archival | Karakeep, Joplin clipper | fetches the internet — offline-only |

**Ideas-only (AGPL/GPL/source-available — never copy code):** Reor, Khoj, Quivr, Onyx, open-webui,
Karakeep, Notesnook, Logseq, SiYuan, Trilium, Vikunja, AppFlowy, obsidian-copilot.

## 5. Where this connects to work already done

- The **id→filename linking fix** (2026-06-19) already closed the most damaging correctness gap and aligned
  grandplan with the canonical name-first model (Foam/Obsidian). Placeholder nodes (P0) are the natural
  next step on that same surface.
- **Track 1** is the concrete, sourced plan for the roadmap's *entity extraction* and *context-aware
  reconcile Slice B* items — LightRAG/LlamaIndex give a copyable path instead of net-new design.
