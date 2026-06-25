# LLM-Wiki Deep-Read: Techniques to Borrow for grandplan

**Date:** 2026-06-19
**Author:** research agent (read-only web research; no code changed)
**Purpose:** Extract concrete, adoptable techniques from well-regarded open-source "LLM-Wiki" / PKM projects for **grandplan** — a native-Windows, fully-OFFLINE second brain (global-hotkey capture → local Ollama LLM organizes a selection into an atomic, lossless Markdown note → written into an Obsidian vault with a knowledge graph + generated plan). Constraints: **offline-only, lossless verbatim preservation, local LLM only, 16GB RAM no-GPU, event-sourced, strict quality gate, MIT-licensed.**

**Special focus:** how each project models **note links and node identity** — by human-readable note **name / file path / Obsidian `[[wikilink]]`** vs by **opaque internal ID** — because grandplan has a suspected bug where the graph links notes **by internal ID** instead of by name/path.

> **Legal frame used throughout:** *Ideas/algorithms are always free to adopt.* **Code** may only be copied (with attribution) from **MIT / Apache-2.0** projects. **AGPL/GPL = copyleft = NOT safe to copy** into MIT grandplan (study only). **Source-available / NOASSERTION / unlicensed = NOT safe to copy** (study only).

---

## TL;DR (read this first)

1. **Every well-regarded project links notes by human-readable name/path via `[[wikilinks]]`, NOT by opaque internal ID.** The only projects that use IDs (Logseq block refs, SiYuan) do so *only for sub-note blocks* and **always resolve the ID to readable anchor text in the UI** — and they pay for it with broken links on export. **grandplan's suspected ID-linking bug is a real bug:** for note-to-note links, the correct identity is the note **name/path rendered as an Obsidian `[[wikilink]]`**.
2. **The "LLM-Wiki pattern" (Karpathy) beats query-time RAG by *incrementally compiling and maintaining* persistent interlinked pages.** It scales to thousands of pages because the LLM **never loads the whole wiki** — it operates per-concept on a bounded "source budget," tracks source→concept dependencies in a small state DB, and only recompiles concepts whose sources changed.
3. **Closest legal templates to copy from:** `obsidian-llm-wiki-local` (MIT) and `llmwiki`/`llm-wiki-compiler` (Apache/MIT). The strongest *non-copyable* design references are Foam (MIT, link resolution model — actually copyable!), Reor (AGPL, auto-link-by-vector), Smart Connections (source-available, block embeddings), Logseq/SiYuan (AGPL, block-id discipline).

---

# Part A — Per-Project Findings

## PRIMARY (closest fit)

### A1. kytmanov/obsidian-llm-wiki-local — *the closest fit; study hardest*
- **Verified:** yes. **Stars:** ~727. **License:** **MIT (copy-safe with attribution).** **Desc:** "Turn your raw notes into a self-improving, interlinked wiki — powered by a local LLM." Implements Karpathy's LLM-Wiki pattern. **100% offline via Ollama** (also supports OpenAI-compatible local endpoints). Python (`src/obsidian_llm_wiki/`).
- **Why it matters:** it is grandplan's constraints, already built — offline, Ollama, drop-Markdown, no embeddings, no vector DB, lossless raw notes, frontmatter-based state, quality annotations, human review gate, git commits. Read its source first before building anything new.
- **Top techniques (BORROW):**
  1. **Three-stage pipeline `ingest → compile → review`** (plus `run`, `watch`, `query`, `maintain`, `lint`, `compare`). *Ingest* uses a **fast LLM (3–8B)** to extract concept names + aliases + quality scores into `state.db`. *Compile* uses a **heavy LLM (7B–14B)** to write one article per concept. *Review* is an interactive approve/reject/diff/edit menu; rejection feedback is fed back into the next compile.
  2. **Per-concept context budgeting to avoid the context bottleneck.** "Source budget = `heavy_ctx / 2` chars." `heavy_ctx` defaults to 32,768 (tuned for 16GB). The model **never loads the whole wiki** — it gathers only the source notes that mention the concept, truncated to the budget. Long notes are chunked at `fast_ctx / 2` so nothing is truncated/lost (matches grandplan's lossless rule).
  3. **No embeddings, no vector DB.** `wiki/index.md` is a flat Markdown routing layer for `olw query`. Simpler, fully offline, deterministic.
  4. **Incremental recompile via source→concept dependency tracking in `state.db`** (SQLite at `.olw/state.db`). Editing `raw/note.md` re-ingests only that note and recompiles only concepts tied to it. Published articles are skipped unless `--force`.
  5. **Hand-edit preservation via body hashes in frontmatter.** Synthesis pages store source-page **body hashes**; `update_in_place` rewrites only when the body still matches the DB-tracked hash. Edit an article in Obsidian and the next run detects the change and skips it. **Raw notes are never modified.**
  6. **`maintain` / `lint --fix`:** orphan detection, stub creation for dangling wikilink targets, **broken-link repair**, alias normalization.
- **LINK / NODE-IDENTITY MODEL (critical):** **By normalized concept NAME → file `wiki/<Concept Name>.md`, linked with Obsidian `[[Related Concept]]`.** "**No internal IDs are used; linking relies on normalized concept names.**" Aliases (e.g. `PC` → `Program Counter`) are extracted at ingest and used to **repair broken wikilinks**. Concept pages link to source pages via `[[Source Page Name]]`; source pages backlink to concepts. **This is exactly the model grandplan should match.**

### A2. lucasastorian/llmwiki — Apache-2.0, Karpathy impl
- **Verified:** yes. **Stars:** ~1.2k. **License:** **Apache-2.0 (copy-safe with attribution + NOTICE).** **Desc:** "Open Source Implementation of Karpathy's LLM Wiki. Upload documents, connect Claude via MCP, write your wiki." Python 54.7% / TypeScript 42.7%. Modules: `api/`, `mcp/`, `web/`, `converter/`, `shared/`.
- **Top techniques (BORROW — but note cloud LLM via MCP/Claude, not offline-default):**
  1. **Autonomous *incremental maintenance* via scheduled routines** that synthesize new sources into existing pages nightly — "tracks what's been processed to avoid redundant work." (Incremental maintain, **not** query-time RAG.)
  2. **Citation graph** + cross-link validation via a `lint` tool (cross-references checked).
  3. **MCP server** exposing read/write/search over the wiki (grandplan already has an MCP server — pattern is validated).
  4. **Graph visualization** of concept relationships; **multi-format converter** (PDF/Office/MD/XLS).
- **LINK / NODE-IDENTITY MODEL:** **By file PATH** in Markdown storage (e.g. `/wiki/concepts/attention.md`), with a **citation graph** tracking page→source references and cross-reference validation. Path/name-based, not opaque IDs.
- **Caveat:** designed around a cloud LLM (Claude via MCP). Offline only if you swap in a local model. Apache-2.0 makes its *code* (e.g. the converter, citation-lint) borrowable.

### A3. Ar9av/obsidian-wiki — MIT, agents maintain the brain
- **Verified:** yes. **Stars:** ~2.3k. **License:** **MIT (copy-safe).** **Desc:** "Framework for AI agents to build and maintain a digital brain through Obsidian wiki using Karpathy's LLM Wiki pattern."
- **Top techniques (BORROW):**
  1. **Four-stage agent loop `ingest → pull info → merge → schema`** where **schema emerges from sources** rather than being fixed upfront — and a **merge** step that updates existing pages / avoids duplication (directly relevant to grandplan's reconcile).
  2. **`.manifest.json` provenance + delta tracking** so only new/changed content is reprocessed (cheaper than re-reading the vault).
  3. **Tiered query-time retrieval** (titles/tags/summaries first, then page bodies) using **Grep/Glob by default** — no embeddings required; optional semantic (QMD). Fully local-capable.
  4. **A dedicated "cross-linker" skill** that discovers *unlinked mentions* and weaves them into the graph.
- **LINK / NODE-IDENTITY MODEL:** **Obsidian `[[wikilinks]]` (by name)**; the cross-linker auto-discovers unlinked mentions and converts them to wikilinks. No opaque IDs.

### A4. atomicstrata/llm-wiki-compiler (a.k.a. `llmwiki`) — MIT, knowledge compiler
- **Verified:** yes. **Stars:** ~1.6k (latest v0.10.0, June 2026). **License:** **MIT (copy-safe).** **Desc:** "The knowledge compiler. Raw sources in, interlinked wiki out. Inspired by Karpathy's LLM Wiki pattern." TypeScript ~96%.
- **Top techniques (BORROW):**
  1. **Two-phase compile producing *typed* pages** (concept / entity / comparison / overview) — typing the node is a cheap signal grandplan could adopt.
  2. **Citation traceability to file + line range:** "paragraphs and claims cite source files and line ranges," validated by `llmwiki lint`. (Strong fit for grandplan's lossless/provenance goals.)
  3. **Incremental compile via source hashes in `.llmwiki/state.json`** + "source ownership" — "unchanged sources do not flow back through the LLM."
  4. **Freshness/stale repair:** pages are tracked as fresh/stale/orphaned/unverified; `llmwiki next` surfaces them; `llmwiki refresh --stale` repairs only affected owners (no full recompile).
  5. **Open Knowledge Format (OKF)** import/export for portable knowledge exchange (provenance preserved under `x-llmwiki`).
- **LINK / NODE-IDENTITY MODEL:** Standard Markdown **wikilinks**; **shared concepts consolidate into a single page** (no duplicate chunks). Identity is **path/slug-driven** within `wiki/concepts/`, `wiki/queries/` (docs do not expose any UUID scheme — paths drive identity).
- **Plus — the key scaling technique → see Part B.1:** **hybrid retrieval "context packs"** = semantic chunk search → BM25 rerank → **wikilink graph expansion** → compact, *citation-aware* evidence pack (`llmwiki context "<task>" --json` / MCP). This is how you serve thousands of pages to an LLM without a context bottleneck.

## SECONDARY (proven PKM linking/graph models)

### A5. foambubble/foam — MIT (link resolution model; ACTUALLY COPYABLE)
- **Verified:** yes. **Stars:** ~17.2k. **License:** **MIT (copy-safe).** **Desc:** "A personal knowledge management and sharing system built on VS Code and GitHub."
- **Top techniques:** plain-Markdown vault as source of truth; `[[wikilink]]` with alias `[[target|alias]]`, autocompletion, heading/section links; **backlinks panel with context previews**; **link-sync-on-rename**; **placeholders view** for dangling links.
- **LINK / NODE-IDENTITY MODEL (the gold standard for grandplan):** **Link text is a human-readable identifier (basename/title); node identity is the file's URI (path-derived).** Each `Resource` = `{uri, title, links, tags, sections, aliases}`. Resolution (`packages/foam-core/src/model/workspace.ts`, `FoamWorkspace.find(reference, baseUri)`) is three-stage: (1) exact URI via trie; (2) **identifier lookup by bare name/title** (`listByIdentifier`); (3) absolute/relative path (auto-appending `.md`). **Ambiguity:** `getShortestIdentifier` adds the *minimum* parent-folder segments to disambiguate same-named notes (`[[folder/note]]`). **Graph** (`graph.ts`, `FoamGraph`) keeps `links` (outgoing) + `backlinks` (incoming) maps, written bidirectionally by `connect()`; misses become **placeholder nodes**; live updates via `onDidAdd/Update/Delete`. **Renames rewrite the link text**, not a stable ID.
- **Takeaway:** This is the *exact* correct model for grandplan: **store the human name in the link; resolve it to a path/URI node; disambiguate by minimal path prefix; track placeholders for misses.** MIT — borrowable.

### A6. reorproject/reor — AGPL-3.0 (study only) — local-embedding auto-linking
- **Verified:** yes. **Stars:** ~8.6k. **License:** **AGPL-3.0 — NOT copy-safe (study ideas only).** **Desc:** "Private & local AI personal knowledge management app."
- **Top techniques (IDEAS):** every note chunked + embedded into **local LanceDB** (Transformers.js embeddings, Ollama LLM — fully local); **automatic "Related Notes" sidebar** via vector similarity (no manual linking); local semantic search + RAG.
- **LINK / NODE-IDENTITY MODEL:** **No wikilinks, no name-links written.** "Links" are **computed at query time from vector similarity** and identified by **`notepath` (file path string)** — never an opaque node ID, never persisted into note text. Schema: `DBEntry = {notepath, content, subnoteindex, timeadded, ...}` + `vector`; results add `_distance`. Related sidebar embeds the open note's first ~500 chars, searches, **excludes self by `NOTE_PATH != '<path>'`**, opens results **by path**.
- **Takeaway:** even a pure-vector system keys everything by **file path**, and surfaces *suggestions* without polluting note bodies. Good model for grandplan's "related notes" *if/when* it adds embeddings — but keep the LLM small (AGPL means: copy nothing, mirror the design).

### A7. brianpetro/obsidian-smart-connections — Source-available (study only) — block-level relations
- **Verified:** yes. **Stars:** ~5.2k. **License:** **"Smart Plugins License" — source-available, NOT OSI, NOT copy-safe.** Ideas only. **Desc:** "Find related notes and excerpts while writing… local embedding model powers semantic search. Zero setup. No API key."
- **Top techniques (IDEAS — well-matched to offline/16GB/no-GPU):**
  1. **Bundled local embedding model via Transformers.js (`BGE-micro-v2`, ~384-dim), CPU in-process, no Ollama needed for embeddings.** Key insight: **embeddings don't need the LLM** — cheap, offline, no GPU.
  2. **Block-level embeddings** (paragraphs/list-items/headings-with-content), enabling "related excerpts," not just related files.
  3. **No LLM in the hot path** for related-notes — pure cosine similarity scales to thousands of notes cheaply.
  4. **In-vault portable index** under `.smart-env/` (`embeddings.ajson`), keyed by path + block, `mtime`-based incremental re-embedding.
- **LINK / NODE-IDENTITY MODEL:** **Human-readable file path + block locator**, not hashes. Record = `path` + `blocks[]`, each block = `text` + `embedding` + **char `offset`/`length`** (sub-key form `path#heading`). Results render as **clickable links by note name** and can be **dragged into a note to create a real `[[wikilink]]`**.

## DIFFERENT (fresh angles on ID vs name linking)

### A8. khoj-ai/khoj — AGPL-3.0 (study only) — RAG second brain
- **Verified:** yes. **Stars:** ~35.2k. **License:** **AGPL-3.0 — NOT copy-safe (ideas only).** **Desc:** "Your AI second brain. Self-hostable."
- **Top techniques (IDEAS):** classic RAG with **local sentence-transformers (`all-MiniLM-L6-v2`, 384-dim, ~22MB, CPU-friendly)**; **offline chat via Ollama / local OpenAI-compatible servers**; multi-format ingest into one index.
- **Offline/RAM caveat (relevant to grandplan):** embedding/retrieval are fine on CPU, but Khoj *recommends 16GB VRAM + GPU* for usable **chat** — **the local LLM generation is the only real RAM/GPU bottleneck on 16GB-no-GPU.** Keep grandplan's organize model small/quantized (echoes the capture-crash OOM finding).
- **LINK / NODE-IDENTITY MODEL:** retrieves **chunks** but **cites by source FILE (path/name)**, not by opaque chunk id. Obsidian client opens the actual file; chat answers list visitable file citations. Internal chunk ids exist but are **never the user-facing link**.

### A9. logseq/logseq — AGPL-3.0 (study only) — pages-by-name, blocks-by-UUID
- **Verified:** yes. **Stars:** ~43.5k. **License:** **AGPL-3.0 — NOT copy-safe.** Local-first Markdown/Org outliner.
- **Top techniques (IDEAS):** plain-text files as source of truth; outliner where every bullet is addressable; automatic backlinks/linked-references; `((...))` block embeds (single-source transclusion); `key:: value` block properties.
- **LINK / NODE-IDENTITY MODEL (the contrast lesson):**
  - **Pages linked by NAME:** `[[Page Name]]` — the title **is** the key; no page IDs.
  - **Blocks referenced by UUID:** `((uuid))`, with the UUID stored **inline in the Markdown** as `id:: <uuid>`.
  - **Kept human-navigable:** the editor **inlines the referenced block's actual text** in place of the raw UUID (hover preview, click-through). The user almost never sees the UUID.
  - **Rename cost:** because pages link by name, renaming **rewrites every `[[link]]`** in every file — fragile (reported failures: aliases not updating, stale refs until re-index, breakage on special chars — issues #2968/#9202/#4356). Block UUID refs survive renames untouched.

### A10. siyuan-note/siyuan — AGPL-3.0 (study only) — everything-by-block-ID
- **Verified:** yes. **Stars:** ~44.5k. **License:** **AGPL-3.0 — NOT copy-safe.** Block-based WYSIWYG PKM (TS + Go).
- **Top techniques (IDEAS):** permanent immutable block IDs surviving any reorganization; block embeds/transclusion; native databases over blocks; SQL queries; zoom-in/focus with breadcrumbs.
- **LINK / NODE-IDENTITY MODEL (the cautionary tale):**
  - **Everything is a block referenced by ID** (docs, headings, paragraphs all get a permanent ID). **ID format:** 14-digit timestamp + 7 random chars (e.g. `20260418142733-x7k9j2m`); filenames use the same scheme (`.sy`).
  - **Storage:** *not* Markdown — `.sy` JSON holds each note's **AST** with block IDs as node IDs, indexed in SQLite. The ID is intrinsic to the structured node → stable across edits/moves.
  - **Kept human-navigable:** UI resolves ID → block **anchor text** + zoom/breadcrumbs + live-updating embeds + backlinks.
  - **The downside they had to solve (the warning for grandplan):** ID-links **do not round-trip to plain Markdown.** Export emits a SiYuan-only URI `[Anchor text](siyuan://blocks/<id>)` that is **dead outside the app**; inter-note links are widely reported **broken on export** (issues #9743/#16038). **This is the structural cost of opaque IDs — exactly the failure mode grandplan's suspected bug would produce in an Obsidian vault.**

---

# Part B — Syntheses

## B.1 — The "LLM-Wiki pattern" and how to SCALE it to thousands of pages

**The pattern (Karpathy, formalized April 2026).** Three layers:
1. **Raw sources** — immutable inputs (grandplan's verbatim captures). *Never modified.*
2. **Wiki** — LLM-generated, interlinked Markdown (concept/entity/summary pages with `[[wikilinks]]`, backlinks, contradiction flags).
3. **Schema** — a `CLAUDE.md`-style instruction file telling the LLM how to maintain the wiki. *(grandplan already has `_grandplan-guide.md` — same idea.)*

**Incremental-maintain vs query-time-RAG — the central choice.** Plain RAG re-retrieves and re-reasons from scratch every query; knowledge never compounds. The LLM-Wiki pattern **compiles knowledge once into durable pages and incrementally maintains them**, so structure, provenance, and cross-links **accumulate**. Karpathy's own run grew to ~100 articles / ~400k words. **grandplan is already on the right side of this** (event-sourced, reconcile updates existing notes) — keep going.

**How to scale to thousands of pages WITHOUT a context bottleneck** (composite of the four primary repos):

1. **Never load the whole wiki into the LLM.** Operate **per concept/page** on a **bounded source budget** (kytmanov: `heavy_ctx / 2` chars; gather only the sources that mention the concept; chunk long inputs at `fast_ctx / 2` so nothing is lost — lossless-safe). This is O(sources-per-concept), not O(vault).

2. **Track source→page dependencies in a tiny state store** (kytmanov `state.db`; llmwiki `.llmwiki/state.json` source hashes + "source ownership"; obsidian-wiki `.manifest.json` deltas). On change, **recompile only affected pages** — "unchanged sources do not flow back through the LLM." grandplan's event log already gives this for free; make the projection step consume it.

3. **Two-tier model routing.** Fast small model (3–8B) for ingest/extraction; heavier (7–14B) only for article generation. Cuts cost ~10x and fits 16GB. (Echoes grandplan's existing cost-aware routing.)

4. **For *retrieval/query* at scale, use a "context pack" (the key technique to BORROW from llmwiki):** **semantic chunk search → BM25 rerank → wikilink graph expansion → compact, citation-aware evidence pack.** The wikilink graph is the cheap part that makes it scale: once you've found a few seed pages, *follow the existing `[[links]]`* to expand context instead of re-embedding everything. **This is why correct name/path-based wikilinks (Part B.2) are not just cosmetic — they are the scaling substrate.** (If links are opaque IDs that don't resolve, graph expansion silently breaks and you fall back to pure vector search, losing the compounding benefit.)

5. **A flat `index.md` routing layer** (kytmanov) is enough for many vaults with *zero* embeddings — fully offline, deterministic, and grandplan-friendly. Add embeddings (CPU MiniLM/BGE-micro, per Smart Connections/Khoj) **only** when name/tag/title retrieval stops being enough; embeddings don't need the LLM and run on CPU.

6. **Freshness as a first-class state** (llmwiki: fresh/stale/orphaned/unverified; `refresh --stale`). Lets you bound maintenance work and surface what needs attention without recompiling the world.

## B.2 — The CORRECT way to model note links (directly applicable to the suspected ID-linking bug)

**Verdict: for note-to-note links, identify nodes by human-readable note NAME/PATH and render them as Obsidian `[[wikilinks]]`. Do NOT link notes by opaque internal ID.** The evidence is unanimous across the projects closest to grandplan:

| Project | Note→note link is by… | Opaque IDs used? |
|---|---|---|
| kytmanov (MIT, closest fit) | **normalized concept NAME → `[[wikilink]]`** | **No** ("no internal IDs are used") |
| llmwiki / lucasastorian (Apache) | file **PATH** + citation graph | No |
| obsidian-wiki (MIT) | **`[[wikilink]]`** (by name) | No |
| llm-wiki-compiler (MIT) | wikilinks; **path/slug** identity | No |
| Foam (MIT) | **name in link text → resolved to path/URI node** | No |
| Reor (AGPL) | **file path** (vector-suggested) | No |
| Smart Connections (src-avail) | **path + `path#heading`**, drag → real `[[wikilink]]` | No (offsets, not hashes) |
| Khoj (AGPL) | cites by **file path/name** | No (chunk ids hidden) |
| Logseq (AGPL) | **pages by NAME**; blocks by UUID | Only for sub-note **blocks** |
| SiYuan (AGPL) | **everything by block ID** | Yes — *and links die on export* |

**The correct model to implement (mirror Foam — MIT, copyable):**
1. **Store the human-readable name in the link itself** (`[[Note Name]]` or `[[Note Name|alias]]`), so the link is legible *in the raw Markdown* and works natively in Obsidian.
2. **Resolve name → node** in a three-stage lookup: exact path/URI → **bare-name/title index** → relative/absolute path (append `.md`). The **node's identity is its file URI/path**; the *link* carries the *name*.
3. **Disambiguate same-named notes by the minimum path prefix** (`getShortestIdentifier`), e.g. `[[folder/Note]]` only when needed.
4. **Build backlinks bidirectionally** (`links` + `backlinks` maps; `connect()` writes both) and **track misses as placeholder nodes** rather than dropping them (kytmanov stubs / Foam placeholders).
5. **Handle renames by rewriting link text** (Foam link-sync-on-rename) — and because grandplan is event-sourced, a rename is just another event the projection replays.
6. **Aliases** (kytmanov) repair broken wikilinks and absorb abbreviations.

**Why the suspected ID bug is genuinely wrong (the two failure modes the projects prove):**
- **Obsidian-invisibility:** Obsidian's graph/backlinks resolve `[[Name]]`. A link by opaque internal ID either renders as a dead `[[a1b2c3…]]` or lives only in a sidecar grandplan never surfaces — i.e. **the knowledge graph is invisible/non-navigable to the human in the very app it writes to.** SiYuan's `siyuan://blocks/<id>` export breakage (issues #9743/#16038) is the exact same failure.
- **Broken graph expansion at scale:** the B.1 scaling technique (follow `[[links]]` to expand context) requires links that resolve to readable pages. ID links that don't resolve silently degrade retrieval to pure vector search and **kill the compounding benefit**.

**When are IDs acceptable?** Only for **sub-note blocks** (a sentence has no stable human name and moves around) — and **only** if you obey the non-negotiable rule both Logseq and SiYuan follow: **the UI/output must NEVER show the raw ID; always resolve it to the referenced block's text + a jump target, and provide a deterministic ID→path/anchor export rewrite.** grandplan links *whole notes*, so it should be **name/path all the way** and not need IDs at all right now.

## B.3 — Prioritized BORROW list

Effort: **S** = hours, **M** = a day or two, **L** = multi-day. Offline-safe = runs with zero network egress.

| # | Technique | Source repo | License | Copy-safe? | Offline-safe? | Effort | Notes |
|---|---|---|---|---|---|---|---|
| 1 | **Fix link model: name/path `[[wikilink]]` + 3-stage resolver + shortest-path disambiguation + bidirectional backlinks + placeholders** | **Foam** | **MIT** | **Yes (code, attribute)** | Yes | **M** | *Top priority — fixes the suspected ID bug.* Port `workspace.ts`/`graph.ts` resolution logic. |
| 2 | **Per-concept source budgeting** (`heavy_ctx/2`, gather-only-mentioning-sources, chunk long inputs) | kytmanov | MIT | Yes (attr.) | Yes | M | The core anti-context-bottleneck mechanism; lossless-safe. |
| 3 | **Source→page dependency tracking → recompile only affected pages** | kytmanov / llmwiki | MIT | Yes (attr.) | Yes | M | grandplan's event log already supplies this; wire into projection. |
| 4 | **Two-tier model routing** (fast 3–8B ingest, heavy 7–14B compile) | kytmanov | MIT | Yes (attr.) | Yes | S | Fits 16GB; grandplan partly has this. |
| 5 | **Hand-edit preservation via body-hash in frontmatter** (`update_in_place` only if hash matches) | kytmanov | MIT | Yes (attr.) | Yes | S | Protects human edits from regeneration. |
| 6 | **Context-pack retrieval: semantic → BM25 rerank → wikilink graph expansion** | llmwiki | MIT | Yes (attr.) | Yes | L | The scale-to-thousands technique; depends on #1 working. |
| 7 | **Alias extraction → broken-wikilink repair + stub/orphan `maintain`/`lint`** | kytmanov | MIT | Yes (attr.) | Yes | M | Keeps the graph healthy at scale. |
| 8 | **Freshness state (fresh/stale/orphaned) + `refresh --stale`** | llmwiki | MIT | Yes (attr.) | Yes | M | Bounds maintenance work. |
| 9 | **Provenance/delta manifest + emergent schema; explicit "cross-linker" pass** | obsidian-wiki | MIT | Yes (attr.) | Yes | M | Strengthens grandplan's reconcile/merge. |
| 10 | **Citation to file + line-range** for lossless provenance | llmwiki | MIT | Yes (attr.) | Yes | M | Aligns with grandplan's lossless rule. |
| 11 | **Typed pages** (concept/entity/comparison/overview) | llm-wiki-compiler | MIT | Yes (attr.) | Yes | S | Cheap node-type signal. |
| 12 | **Block-level CPU embeddings (BGE-micro/MiniLM) keyed by `path#heading`, drag→`[[wikilink]]`** | Smart Connections / Khoj | src-avail / AGPL | **No (ideas only)** | Yes | L | *Re-implement* with own code; embeddings need no GPU/LLM. Defer until name retrieval insufficient. |
| 13 | **Auto "related notes" by vector, keyed by path, never persisted into note body** | Reor | AGPL | **No (ideas only)** | Yes | L | *Re-implement.* Suggestions stay out of note bodies. |
| 14 | **Block-ID discipline IF blocks ever needed: never show raw ID; resolve to text; deterministic export rewrite** | Logseq / SiYuan | AGPL | **No (ideas only)** | Yes | L | Only for sub-note refs; grandplan likely doesn't need it yet. |

---

# Part C — What this reveals grandplan may be doing WRONG

1. **The ID-linking bug is real and high-impact.** Every comparable project links notes by name/path; the only ID-users (SiYuan) demonstrably **break links on export to Markdown** — the exact environment grandplan targets (an Obsidian vault). Fix to `[[Note Name]]` with a Foam-style resolver (BORROW #1). Until then, grandplan's graph is likely invisible/non-navigable inside Obsidian and its wikilink-graph retrieval (if any) is degraded.
2. **If grandplan loads large context for organize/reconcile, adopt per-concept source budgeting (#2).** The reference projects prove the whole-neighborhood approach must still be *bounded* (`heavy_ctx/2`) and dependency-scoped, or it won't scale past ~hundreds of notes on 16GB.
3. **Keep the LLM small.** Khoj confirms the LLM (not embeddings/retrieval) is the only real RAM bottleneck on 16GB-no-GPU — consistent with grandplan's capture-crash OOM finding. Embeddings, if added, are CPU-cheap.
4. **Add alias + broken-link repair + placeholders/stubs (#7).** Without them, an LLM-generated graph accumulates dangling links and orphans as it grows.
5. **Don't put computed "related notes" into note bodies** (Reor model) — keep suggestions out of the lossless verbatim content; surface them in a sidebar/section or as reviewed proposals.

---

## Verification & sources

All 13 repos were fetched and verified to exist; star counts/licenses read off their GitHub pages (June 2026). Star counts are point-in-time approximations.

- kytmanov/obsidian-llm-wiki-local (MIT, ~727★); lucasastorian/llmwiki (Apache-2.0, ~1.2k★); Ar9av/obsidian-wiki (MIT, ~2.3k★); atomicstrata/llm-wiki-compiler (MIT, ~1.6k★)
- foambubble/foam (MIT, ~17.2k★); reorproject/reor (AGPL-3.0, ~8.6k★); brianpetro/obsidian-smart-connections (source-available, ~5.2k★)
- logseq/logseq (AGPL-3.0, ~43.5k★); siyuan-note/siyuan (AGPL-3.0, ~44.5k★); khoj-ai/khoj (AGPL-3.0, ~35.2k★)
- Karpathy LLM-Wiki pattern: https://www.mindstudio.ai/blog/andrej-karpathy-llm-wiki-knowledge-base-claude-code ; https://levelup.gitconnected.com/beyond-rag-how-andrej-karpathys-llm-wiki-pattern-builds-knowledge-that-actually-compounds-31a08528665e ; https://aaronfulkerson.com/2026/04/12/karpathys-pattern-for-an-llm-wiki-in-production/
- Foam source: `packages/foam-core/src/model/workspace.ts`, `graph.ts`
- Reor source: `electron/main/vector-database/schema.ts`, `src/components/Sidebars/SimilarFilesSidebar.tsx`
- SiYuan/Logseq export-break issues: siyuan #9743/#16038; logseq #2968/#9202/#4356

> **Action item:** Before copying any code, confirm the live `LICENSE` file of each MIT/Apache repo and include the required attribution/NOTICE. Treat AGPL (Reor, Khoj, Logseq, SiYuan) and the source-available Smart Connections as **design references only — copy no code.**
