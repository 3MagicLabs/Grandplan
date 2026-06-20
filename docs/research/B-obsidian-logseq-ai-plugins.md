# Research B — Obsidian / Logseq / SiYuan / Foam Ecosystem: AI Organization, Auto-Linking, Semantic Search & Graph/Backlink Tools

> Scope: local-LLM-friendly tools for AI note organization, auto-linking, semantic search, and graph/backlinks in the Markdown PKM ecosystem. Plus a deep dive on how Foam/Obsidian/Logseq/SiYuan MODEL links & backlinks — directly relevant to grandplan's linking design.
> Method: read-only research. All star counts and licenses verified via `gh api repos/<owner>/<name>` and `gh api search/repositories` on **2026-06-19**. Where a license shows `NOASSERTION` (GitHub couldn't auto-classify), the actual LICENSE file was fetched and inspected.
> Out of scope (other agents): standalone self-hosted RAG apps, memory libraries, task/planning apps. (AnythingLLM / Khoj are noted only for their linking-relevant techniques, not as primary targets.)

---

## 1. Verified Project Inventory

Legend — **License class**: `COPYABLE` = MIT/Apache/BSD (can vendor/port code) · `IDEAS` = AGPL/GPL/source-available/custom (study the design, do not copy code into an MIT project) · `MIT*` = custom but MIT-equivalent grant.

| # | Project | Stars | License | Class | Offline / local-LLM fit |
|---|---------|------:|---------|-------|--------------------------|
| 1 | [obsidian-smart-connections](https://github.com/brianpetro/obsidian-smart-connections) | 5,183 | Smart Plugins License Agreement (MIT-style grant) | MIT* | **Excellent** — ships a local embedding model, "Zero setup, no API key" |
| 2 | [obsidian-copilot](https://github.com/logancyang/obsidian-copilot) | 7,244 | AGPL-3.0 | IDEAS | Good — supports Ollama / local models; "Copilot Plus" tier is cloud |
| 3 | [obsidian-smart-composer](https://github.com/glowingjade/obsidian-smart-composer) | 2,292 | MIT | COPYABLE | **Excellent** — vault-aware RAG + local model support (Ollama) |
| 4 | [obsidian-textgenerator-plugin](https://github.com/nhaouari/obsidian-textgenerator-plugin) | 1,954 | MIT | COPYABLE | Good — template engine; OpenAI/Anthropic/Google **+ local models** |
| 5 | [hinterdupfinger/obsidian-ollama](https://github.com/hinterdupfinger/obsidian-ollama) | 1,018 | MIT | COPYABLE | **Excellent** — pure Ollama; offline by design (last push 2024) |
| 6 | [foambubble/foam](https://github.com/foambubble/foam) | 17,234 | MIT (per repo metadata) | COPYABLE | **Excellent** — local VSCode files; no AI, but the canonical link/backlink reference |
| 7 | [obsidian-dataview](https://github.com/blacksmithgu/obsidian-dataview) | 9,081 | MIT | COPYABLE | **Excellent** — fully local query engine over Markdown + frontmatter |
| 8 | [obsidian-tasks](https://github.com/obsidian-tasks-group/obsidian-tasks) | 3,815 | MIT | COPYABLE | **Excellent** — local; inline metadata + query DSL |
| 9 | [khoj](https://github.com/khoj-ai/khoj) | 35,209 | AGPL-3.0 | IDEAS | Good (self-host) — local LLM + semantic search; has an Obsidian plugin |
| 10 | [note-companion (file-organizer-2000)](https://github.com/Nexus-JPF/note-companion) | 847 | MIT | COPYABLE | Partial — auto-organize/auto-tag/auto-name; cloud-leaning but Ollama option |
| 11 | [jacksteamdev/obsidian-mcp-tools](https://github.com/jacksteamdev/obsidian-mcp-tools) | 827 | MIT | COPYABLE | **Excellent** — exposes the vault over MCP (matches grandplan's MCP server) |
| 12 | [briansunter/logseq-plugin-gpt3-openai](https://github.com/briansunter/logseq-plugin-gpt3-openai) | 743 | MIT | COPYABLE | Partial — OpenAI-first, but configurable base URL → Ollama |
| 13 | [zolrath/obsidian-auto-link-title](https://github.com/zolrath/obsidian-auto-link-title) | 693 | MIT | COPYABLE | N/A (network fetch for titles); the *pattern* is offline-portable |
| 14 | [solderneer/obsidian-ai-tools](https://github.com/solderneer/obsidian-ai-tools) | 274 | MIT | COPYABLE | Partial — Supabase pgvector semantic search reference |
| 15 | [bbawj/obsidian-semantic-search](https://github.com/bbawj/obsidian-semantic-search) | 151 | GPL-3.0 | IDEAS | Good — embedding-based note + heading suggestion (Rust/WASM) |
| 16 | [siyuan-note/siyuan](https://github.com/siyuan-note/siyuan) | 44,517 | AGPL-3.0 | IDEAS | **Excellent** (self-host) — block-database PKM, block-ref identity model |
| 17 | [kdnk/obsidian-automatic-linker](https://github.com/kdnk/obsidian-automatic-linker) | 36 | Apache-2.0 | COPYABLE | **Excellent** — converts bare text → `[[wikilinks]]` by matching note names (no network) |
| 18 | [Firefox2100/siyuan-ai-companion](https://github.com/Firefox2100/siyuan-ai-companion) | 15 | GPL-3.0 | IDEAS | Good — SiYuan-as-knowledge-base + LLM API companion |

Honorable mentions / cross-references (primary scope belongs to other agents): [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) (61,822★, MIT — local-first agent + vector DB), [Quartz](https://github.com/jackyzha0/quartz) (12,555★, MIT — static-site generator with excellent wikilink/transclusion resolution worth studying for link rendering), [contextplus](https://github.com/forloopcodes/contextplus) (1,923★, MIT).

---

## 2. Per-Project Techniques, Link Model, and Gaps vs grandplan

### 2.1 obsidian-smart-connections (5,183★, MIT-style) — **most relevant overall**
- **Techniques:** (1) bundled local embedding model (transformers.js) → zero-setup semantic search, no API key; (2) "connections" panel surfaces top-N similar notes *while writing* — a **link-suggestion copilot**; (3) block-level + note-level embeddings (chunking); (4) results shown in BOTH list and graph view; (5) `.smart-env` on-disk embedding cache keyed to content.
- **Link/identity model:** operates over Obsidian's native `[[filename]]` links; its own unit of identity is a **content embedding** per note/block (path + heading anchor), not a stable id.
- **Offline-fit:** Excellent (the gold standard for offline semantic links).
- **grandplan LACKS:** proactive *link suggestion at write time* ("you should link this note to X"). grandplan computes typed edges but does not surface "candidate links you haven't made yet" from embedding similarity. Smart Connections is the reference implementation of that loop, and it is offline.

### 2.2 obsidian-copilot (7,244★, **AGPL — ideas only**)
- **Techniques:** (1) vault QA via RAG; (2) "relevant notes" sidebar; (3) command-palette custom prompts; (4) Ollama/local backend; (5) chunked indexing with persisted vector store.
- **Link model:** native Obsidian links; RAG retrieval is path/heading-anchored.
- **Gap:** mature **prompt-template / custom-command UX**. Do NOT copy code (AGPL); borrow the UX pattern.

### 2.3 obsidian-smart-composer (2,292★, **MIT**) — **most copyable RAG**
- **Techniques:** (1) `@`-mention to pull specific notes/folders into context; (2) **semantic + keyword (hybrid) search** over the vault; (3) one-click *apply edits* to a note (diff/patch UX); (4) local model (Ollama) support; (5) PGlite/local vector store.
- **Link model:** native links; context selection via mentions resolves note → path.
- **Offline-fit:** Excellent. MIT → portable.
- **grandplan LACKS:** the **"apply suggested edit with a diff review"** UX — grandplan's contextual reconciler proposes status changes, but Smart Composer's one-click diff-apply is a cleaner review surface to borrow for Slice B.

### 2.4 obsidian-textgenerator (1,954★, MIT)
- **Techniques:** (1) Handlebars-style **templates** with frontmatter/context variables; (2) provider-agnostic (incl. local); (3) "extract & generate from selection" — *exactly grandplan's capture shape*; (4) template marketplace.
- **Gap:** a **templated prompt library** so organization prompts are user-editable, not hardcoded.

### 2.5 hinterdupfinger/obsidian-ollama (1,018★, MIT)
- **Techniques:** minimal, clean Ollama integration; user-defined commands map a prompt → selection transform; streaming responses.
- **Offline-fit:** Excellent, zero cloud. The simplest reference for a robust Ollama adapter (compare against grandplan's `ollama_organizer.py`).

### 2.6 foambubble/foam (17,234★, MIT) — **the canonical link/backlink reference**
- **Link/identity model (the important part):**
  - **Two link kinds:** *identifier links* `[[filename]]` / `[[folder/filename]]` (resolved by name across the whole workspace, **shortest unambiguous suffix wins**) and *path links* `[[./file]]`, `[[../x]]`, `[[/root/x]]` (resolved by file path).
  - **Placeholders are first-class:** a `[[wikilink]]` with no target file is a **placeholder node** in the graph, styled differently. This lets you link to ideas before they exist — and see "what I intend to write."
  - **Backlinks** are derived by scanning all wikilinks workspace-wide and inverting the edge set.
  - **Link Reference Definitions:** on save, Foam appends standard Markdown `[id]: path 'title'` definitions at the file bottom so the wikilinks degrade gracefully into **portable, plain-Markdown links** for any parser (GitHub, Pandoc).
- **Offline-fit:** Excellent (no AI, just files).
- **grandplan LACKS:** (a) **placeholder nodes as graph citizens** — grandplan deliberately *skips* links to non-existent targets (`vault.py:244` "any `[[…]]` to a non-existent note renders as a phantom node") to avoid clutter, which is the opposite trade-off from Foam; (b) **link-reference-definitions** for portability outside Obsidian.

### 2.7 obsidian-dataview (9,081★, MIT)
- **Techniques:** (1) treat frontmatter + inline `key:: value` fields as a **queryable database**; (2) DQL + JS query API; (3) implicit fields (file.name, file.mtime, file.inlinks/outlinks). `file.inlinks`/`file.outlinks` are a clean **backlink API** over the link index.
- **grandplan LACKS:** an inline-field convention (`key:: value`) — grandplan uses YAML frontmatter only; Dataview's inline fields are a lighter way to attach typed metadata mid-note.

### 2.8 obsidian-tasks (3,815★, MIT)
- **Techniques:** inline emoji/text metadata grammar on a single line, parsed into structured task objects, queried by a filter DSL. Relevant as a **lossless inline-metadata-in-Markdown** pattern (grandplan is lossless-first).

### 2.9 khoj (35,209★, **AGPL — ideas only**)
- **Techniques:** local LLM + embeddings; incremental indexer; "similar notes"; Obsidian plugin client. Strong **incremental re-index on file change** design (study, don't copy).

### 2.10 note-companion / file-organizer-2000 (847★, MIT)
- **Techniques:** (1) AI **auto-folder placement**; (2) AI **auto-tagging**; (3) AI **auto-rename** from content; (4) "similar files." Directly parallels grandplan's `llm_placer.py`. MIT → portable patterns for placement heuristics.

### 2.11 jacksteamdev/obsidian-mcp-tools (827★, MIT)
- **Techniques:** exposes vault search/read/templates over **MCP** for external agents — validates grandplan's own agent-vault MCP server design; borrow tool-surface shape (search, get-note, get-backlinks).

### 2.12 briansunter/logseq-plugin-gpt3-openai (743★, MIT)
- **Techniques:** block-scoped prompt commands in Logseq's outliner; configurable API base (→ Ollama). Shows the **block-as-unit** UX grandplan doesn't have.

### 2.13 zolrath/obsidian-auto-link-title (693★, MIT)
- **Technique:** intercept a pasted URL → fetch + insert a titled link. The *interception/auto-format-on-paste* pattern is portable (grandplan does its own resource extraction); title fetch itself is online-only.

### 2.14 solderneer/obsidian-ai-tools (274★, MIT) & 2.15 bbawj/obsidian-semantic-search (151★, GPL)
- **solderneer:** pgvector embeddings + semantic search reference (MIT, portable).
- **bbawj:** **suggests both notes AND headings** to link to via embeddings, surfaced as autocomplete — a finer-grained link-suggestion than Smart Connections (GPL → ideas only). grandplan LACKS heading-level link targets.

### 2.16 siyuan-note/siyuan (44,517★, **AGPL — ideas only**) — block-identity reference
- **Link/identity model:** every **block has a stable id** (timestamp-based, e.g. `20210808180117-6v0mkxr`); links and embeds reference blocks by that id, NOT by name/path. Renaming a document or moving a block **never breaks references** because identity is decoupled from name and location. This is the strongest "id-first" model in the ecosystem.
- **grandplan LACKS:** block-level stable ids. grandplan has note-level stable `id` (in frontmatter) but links target the *filename slug*, with `id` only as a fallback alias. SiYuan/Logseq show the fully id-first alternative.

### 2.17 kdnk/obsidian-automatic-linker (36★, Apache-2.0) — **offline auto-linker**
- **Technique:** scans note text and **auto-converts bare mentions of existing note names into `[[wikilinks]]`** on save — purely local string/trie matching against the vault's note-name index, no LLM, no network.
- **grandplan LACKS:** automatic *mention → link* densification. grandplan only links via LLM-emitted typed edges; it never says "this note mentions 'Project X' which exists → link it." Apache-2.0 → safely portable.

---

## 3. Synthesis

### (a) The canonical correct way to model note links & backlinks

The ecosystem has converged on **two competing-but-combinable** identity models:

1. **Name/path resolution (Obsidian / Foam) — best default for a Markdown-native, human-readable, offline vault.**
   - Links are written by **human-readable name** (`[[Title]]`), resolved against a workspace-wide name index using **"shortest unambiguous form"**: bare filename when unique, else the shortest distinguishing path. Resolution order (per Obsidian): exact filename (ext-insensitive, case-insensitive) → normalized (spaces/`-`/`_` equivalent) → explicit path.
   - **Disambiguation** = automatically promote a bare name to a path when two notes share a name.
   - **Backlinks** = invert the global wikilink edge set (scan all `[[…]]`, group by target).
   - **Placeholders** = a wikilink with no target is a real graph node (Foam) — link before you write.
   - **Portability** = auto-generate Markdown link-reference-definitions so wikilinks degrade to plain links (Foam).
   - **Best reference repo:** **Foam** ([github.com/foambubble/foam](https://github.com/foambubble/foam), MIT) — cleanest, copyable implementation of identifier-vs-path links, placeholders, and backlink inversion. Its `core` model (workspace + graph + resolver) is the single best thing to study/port.

2. **Stable-id resolution (Logseq / SiYuan) — best when notes are heavily renamed/moved/merged.**
   - Identity is a **stable id** (UUID in Logseq, timestamp id in SiYuan) decoupled from name and path; rename/move never breaks links. Block-level ids enable transclusion of a single sentence.

**Recommendation for grandplan:** grandplan already does the *correct hybrid* — filename-slug links for human readability + a stable `id` in frontmatter `aliases` as the durable fallback + collision suffix `-<id6>` to never clobber. This matches Obsidian's name-first model with an id safety net. The two real gaps versus the canonical model are **(i) placeholder nodes** (grandplan suppresses them; Foam embraces them — reconsider: a placeholder set is exactly "what the plan still needs") and **(ii) link-reference-definitions** for non-Obsidian portability. Going fully id-first (SiYuan-style) is *not* recommended — it sacrifices the human-readable, grep-able, offline-Markdown property that is a grandplan non-negotiable.

### (b) Top 5 borrowable techniques

| # | Technique | Source (repo) | License / safe to copy? | Offline-safe? | Effort | Why for grandplan |
|---|-----------|---------------|-------------------------|---------------|--------|-------------------|
| 1 | **Write-time link suggestions from embedding similarity** ("notes you should link") | obsidian-smart-connections | MIT-style grant — **code portable**; or reimplement | **Yes** (bundled local embeddings) | M | grandplan has `st_embedder` already; add a "candidate links not yet made" surface to the reconcile/review UI |
| 2 | **Offline mention→wikilink densification** (auto-link existing note names found in body text) | kdnk/obsidian-automatic-linker | Apache-2.0 — **copyable** | **Yes** (pure string/trie match) | S | Cheap recall boost: connect notes the LLM didn't explicitly edge, no model call |
| 3 | **Placeholder nodes as first-class graph citizens** + auto-generated link-reference-definitions | foambubble/foam | MIT — **copyable** | **Yes** | M | Surfaces "intended-but-unwritten" artifacts (great for a *plan*); LRDs make the vault portable beyond Obsidian |
| 4 | **One-click diff-apply review UX** for AI-proposed note edits | obsidian-smart-composer | MIT — **copyable** | **Yes** | M | Directly upgrades contextual-reconcile Slice B (propose changes to existing notes) with a clean accept/reject diff |
| 5 | **User-editable prompt templates** for organization/extraction | obsidian-textgenerator (impl) / obsidian-copilot (UX, AGPL→ideas) | textgen MIT copyable; copilot **ideas only** | **Yes** | S–M | Move grandplan's hardcoded organize/reconcile prompts into editable templates; offline-safe |

**Notes on license hygiene:** Copy code only from **MIT/Apache** sources (Foam, Smart Composer, automatic-linker, textgenerator, note-companion, hinterdupfinger/obsidian-ollama, dataview, tasks, mcp-tools). For **AGPL/GPL** sources (copilot, khoj, siyuan, bbawj/semantic-search) and **source-available** ones, study the *design only* — do not vendor code into MIT-licensed grandplan. Smart Connections' "Smart Plugins License Agreement" reads as an MIT-equivalent grant (verbatim: "Permission is hereby granted, free of charge … to deal in the Software without restriction"), so its code is effectively copyable — but pin the exact commit's LICENSE before vendoring.
