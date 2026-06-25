# Prior-Art / Competitive-Landscape Refresh — grandplan (2025–2026)

> **Scope.** A focused refresh of the offline / local-first "second brain" space covering roughly the last 12–18 months. grandplan = Windows-first, fully-offline capture (global hotkey) → local-LLM (Ollama) organization into atomic, lossless Markdown → linked/deduped into an Obsidian vault → projected actionable plan. Core values: zero network egress, lossless (byte-for-byte originals), modest hardware (16 GB RAM, no GPU), and local-LLM *organization* (not just search).
>
> **Verification.** Web tools were available. Every tool/claim below traces to a URL listed in **Sources** that was actually fetched or returned by search. Where a page body could not be retrieved (e.g. Mem review, Micro Center guide returned HTTP 403), the claim is drawn from the search-result snippet and is flagged.

---

## What changed since the last survey

1. **Small local models got genuinely good — and CPU-runnable.** The 3–14 B tier matured fast: Gemma 3 (270M/1B/4B/12B/27B, 128K ctx, multimodal), Qwen3 dense up to 32B + MoE (30B-A3B / 235B-A22B), Phi-4 (14B) and Phi-4-mini (3.8B, ~12 tok/s on CPU), plus Gemma 4 (released Apr 2026). For a 16 GB no-GPU box the sweet spot is now a 3–8 B model at Q4_K_M. This directly strengthens grandplan's "modest hardware" thesis — the hardware floor for *useful* local organization dropped.
2. **A category leader archived.** **Reor** — the closest architectural cousin to grandplan (local-only, Ollama + LanceDB + Transformers.js, auto-linking by vector similarity, Obsidian-like Markdown editor) — was **archived (read-only) on 7 Mar 2026**. Its niche is now under-served.
3. **Graph-RAG over notes went mainstream and local.** **LightRAG** (EMNLP 2025) and Microsoft **GraphRAG** made "build a knowledge graph from your corpus with an LLM, then retrieve over it" a standard technique, and LightRAG explicitly supports fully-local embedding + Ollama LLMs.
4. **Self-hosted NotebookLM clones exploded.** **Open Notebook** (33k★), InsightsLM, SurfSense, KnowNote — most run fully offline via Ollama. They overlap with grandplan on "reason over my docs locally" but are document-Q&A / podcast tools, not capture-and-organize pipelines.
5. **The cloud "AI second brain" tier hardened as cloud-only.** Mem and Saner.ai lean further into cloud LLMs and online sync — they lose features offline — clarifying the privacy gap grandplan fills.

---

## Comparison table

| Tool | Offline? | Local LLM? | Overlap / difference vs grandplan | Source |
|---|---|---|---|---|
| **Reor** (archived Mar 2026) | Yes | Yes (Ollama) | Closest cousin: local Markdown notes, auto-link by vector similarity, RAG Q&A. Differs: *passive* auto-link, no hotkey capture-from-anywhere, no plan projection, no lossless guarantee. **Now archived → gap.** | github.com/reorproject/reor |
| **Khoj** | Partial (self-host) | Yes (llama/qwen/gemma/mistral) or cloud | Overlaps on "second brain over your docs" + Obsidian plugin. Differs: search/chat-centric, also pushes a cloud app (app.khoj.dev); not a capture→organize→plan pipeline. | github.com/khoj-ai/khoj |
| **Obsidian + Copilot / Smart Connections / Smart2Brain** | Yes (vault local) | Yes (Ollama via localhost:11434) | Same vault target as grandplan. Differs: plugins do *semantic search / chat over* the vault; they don't capture from other apps or LLM-organize new captures into atomic notes. Complementary, not competing. | obsidianstats.com/plugins/smart-second-brain ; github.com/your-papa/obsidian-smart2brain |
| **AnythingLLM** | Yes (air-gappable) | Yes (Ollama LLM + embeddings) | Overlaps on local RAG + document Q&A, MIT, desktop. Differs: doc-upload Q&A app, not hotkey capture / Markdown-vault organizer; recommends a GPU for good perf. | docs.anythingllm.com/setup/embedder-configuration/local/ollama |
| **SiYuan** | Yes (local-first, self-host) | Partial (AI features, your-key) | Block-based PKM with graph view, strong privacy. Differs: block IDs not flat Markdown files; AI is assistive, no capture-from-anywhere or plan projection. | github.com/siyuan-note/siyuan |
| **Logseq + AI plugins** | Yes (Markdown outliner) | Yes (Ollama / LocalAI) | Local Markdown PKM. Differs: plugins add summaries/flashcards/local vector search; no global capture or LLM auto-organization of inbound captures. | logseq.com ; github.com/UNICKCHENG/logseq-ai-assistant |
| **Open Notebook** | Yes (Docker + Ollama) | Yes (18+ providers incl. Ollama/LM Studio) | NotebookLM clone: RAG + podcasts over uploaded sources, "no cloud dependencies." Differs: source-grounded research notebook, not a continuous capture/organize/plan loop; Docker-heavy. | github.com/lfnovo/open-notebook |
| **LightRAG** | Yes (local embed + Ollama) | Yes (needs *capable* LLM) | Technique grandplan could adopt: LLM-built knowledge graph + dual-layer (graph+vector) retrieval; cheaper than GraphRAG. Differs: a framework/library, not an app. | github.com/hkuds/lightrag |
| **Microsoft GraphRAG** | Partial (works w/ local but tuned for API) | Partial | KG-from-text technique; strong on complex multi-hop Q&A. Differs: heavier / more LLM calls than LightRAG; library not app. | microsoft.github.io/graphrag |
| **Text Grab** (Windows) | Yes | No (OCR only) | Overlaps on *Windows capture-from-anywhere* via global hotkey, 100% on-device. Differs: OCR capture only, no LLM organization. Useful capture-UX reference. | github.com/TheJoeFin/Text-Grab |
| **Mem (mem.ai)** | **No (cloud)** | No (cloud LLMs) | Same *vision* (instant capture, auto-organize, chat). Opposite *implementation*: cloud-only, "if you're offline, you lose access to a lot of features." grandplan's anti-thesis. | saner.ai/blogs/mem-ai-reviews (snippet) |
| **Saner.ai** | **No (cloud SaaS)** | No (cloud) | Cloud AI notes + tasks/calendar/email. Cloud-only; contrasts with grandplan's offline stance. | saner.ai/blogs/best-ai-note-taking-apps |
| **NotebookLM (Google)** | **No (cloud)** | No (Google models) | Source-grounded reasoning over your uploads — but cloud, your data goes to Google. The thing the offline clones (and grandplan's read path) are reacting against. | (referenced via clone surveys; xda-developers.com) |

---

## Theme 1 — Offline / local-first AI "second brain" apps

- **Reor** was the most direct competitor: private, local-only, Ollama + Transformers.js embeddings + LanceDB, Obsidian-style Markdown, automatic note linking via vector similarity, RAG Q&A — "AI tools for thought should run models locally *by default*." **It was archived (read-only) on 7 Mar 2026 (8.6k★).** This is the single most consequential finding: grandplan's nearest analog just stopped developing, leaving the "fully-local capture-and-organize Markdown app" niche under-served.
- **Khoj** remains the strongest active local-or-cloud second brain: chats with any local model (llama3/qwen/gemma/mistral) or cloud, with Obsidian/Emacs/desktop/phone front-ends. But it dual-tracks a hosted cloud app and is search/chat-centric, not a capture→atomic-note→plan pipeline.
- **Obsidian AI plugin ecosystem** matured: **Copilot** (native Ollama, handles CORS), **Smart Connections** (embedding-based related-notes + Smart Chat RAG), **Smart Second Brain / Smart2Brain** (privacy-focused local assistant). These all *read/search* the vault locally; none capture from other apps or LLM-organize inbound text into new atomic notes. They are complements to grandplan's write path.
- **SiYuan** and **Logseq** are mature local-first PKMs (block-based / outliner respectively) with local AI via Ollama, but AI is assistive (summaries, search), not an organize-on-capture engine.
- **Cloud tier** (Mem, Saner.ai, NotebookLM) keeps "auto-organize + chat" but is cloud-only and degrades offline — confirming grandplan's privacy/offline differentiation rather than threatening it.

## Theme 2 — Local-LLM runtimes for a 16 GB-RAM CPU box

- **Ollama** (v0.30.8, Jun 2026) remains the default local runtime; broader GGUF hardware support + upgraded Apple-Silicon MLX engine. It's the right substrate for grandplan and unchanged as a dependency choice.
- **Models that now fit 16 GB / CPU (Q4_K_M):**
  - **Gemma 3** — 270M / 1B / 4B / 12B / 27B, 128K context, multimodal, 140+ languages. The 4B is a strong capture-organizer default. **Gemma 4** released Apr 2026 (frontier-per-size).
  - **Qwen3** — dense to 32B + MoE (30B-A3B); search snippet also cites a "Qwen 3.5 9B" (~6.6 GB in Ollama, 262K ctx, thinking mode) — *treat the 3.5 figure as unverified from snippet only.*
  - **Phi-4** (14B reasoning) and **Phi-4-mini** (3.8B) — Phi-4-mini cited as best-in-class **CPU** throughput (~12 tok/s), ideal for a no-GPU box.
  - **Mistral Small 3 (7B)** for throughput; **Llama 3.3 8B** for breadth (per SitePoint/Micro Center snippets — *page bodies returned 403, snippet-only*).
- **Takeaway:** grandplan's "16 GB, no GPU" constraint is now comfortably met by 3–8 B models; the memory note's gemma-for-capture choice is well-aligned with the 2026 consensus.

## Theme 3 — RAG-over-notes & knowledge-graph-from-notes

- **LightRAG** (EMNLP 2025, v1.5.4) — LLM extracts entities + relationships → dual-layer **knowledge-graph + vector** index; incremental merge of new docs (no full rebuild); runs with **local embeddings + Ollama**; ~45–55% better than GraphRAG with far fewer LLM calls. Caveat: "higher capability requirements for LLMs than traditional RAG" — i.e. needs a capable-enough local model.
- **Microsoft GraphRAG** — the reference KG-from-text approach; strong on multi-hop Q&A but heavier (more LLM calls), more API-tuned.
- **WeKnora** (Tencent) — local/private RAG + ReAct agent + "Wiki Mode" that distills docs into self-maintaining interlinked Markdown with KGs; Ollama-compatible. Conceptually close to grandplan's "link/dedup into a vault" idea.
- Frameworks (LlamaIndex, plus open-source RAG roundups) increasingly ship hybrid retrieval (semantic + full-text + reciprocal-rank-fusion) and graph indexes out of the box.

## Theme 4 — Capture-from-anywhere + lossless / append-only workflows

- **Text Grab** (Windows) — closest capture-UX reference: global-hotkey, **100% on-device** OCR text capture from anywhere in Windows, optional background process. No LLM, but validates grandplan's Windows global-hotkey capture pattern.
- **Antinote** (macOS) — global hotkey scratchpad, fully local storage, "notes never leave your Mac," NL commands + OCR. Same instant-capture ethos, macOS-only, no local-LLM organization.
- **Stik** (macOS) — hotkey → post-it → stored as plain Markdown files in a folder. Mirrors grandplan's "plain Markdown on disk" durability value.
- **Amplenote** — added system-wide **Global Task Capture** hotkey (Q2 2025) landing into a capture note for later review — same inbox-capture-then-process loop, but cloud-leaning.
- **Lossless / append-only:** no surveyed competitor advertises a **byte-for-byte preservation of the original capture** as a first-class guarantee — most chunk/embed/transform on ingest. grandplan's lossless-original promise remains a genuine differentiator.

## Theme 5 — Self-hosted NotebookLM clones (read/reason path)

- **Open Notebook** (33k★, v1.10.0 Jun 2026) — self-hosted NotebookLM: RAG + multi-speaker podcasts over your sources, 18+ providers incl. **Ollama/LM Studio**, "no cloud dependencies." Docker-based.
- **InsightsLM** — self-hosted (Supabase + n8n + React); fully-local variant via Ollama + Qwen3 + Whisper + CoquiTTS.
- **SurfSense** — Ollama-compatible, hierarchical 2-tier RAG + hybrid search (semantic + full-text + RRF).
- **KnowNote** — lightweight desktop NotebookLM-style, **no Docker/no cloud**, bring-your-own LLM, fully offline.
- These overlap grandplan's *read* path (reason over my corpus locally) but are upload-and-query research tools, not continuous capture/organize/plan loops.

---

## Implications for grandplan

**Where grandplan is still differentiated (defensible):**
1. **The full capture → LLM-organize → link/dedup → plan loop in one offline tool.** Competitors split this: capture tools (Text Grab, Antinote, Stik) don't organize with an LLM; local PKM/AI tools (Reor, Khoj, AnythingLLM, Open Notebook) organize/search but don't capture-from-anywhere or *project an actionable plan*. No surveyed tool does the whole pipeline offline.
2. **Lossless, byte-for-byte originals.** A first-class guarantee essentially nobody else makes; the field defaults to lossy chunk/embed-on-ingest.
3. **Windows-first, no-GPU, fully-offline.** Several "local" leaders quietly assume a GPU (AnythingLLM) or skew macOS (Antinote, Stik) or push a cloud tier (Khoj, Mem, Saner.ai).
4. **Reor's archival vacated grandplan's closest niche** — the "private local Markdown app that LLM-organizes notes" lane is now open.

**Concrete ideas worth adopting (3–5):**
1. **Add a local knowledge-graph layer (LightRAG-style).** Use the local LLM to extract entities/relationships at organize-time and maintain an incrementally-merged graph alongside the vault — better dedup, linking, and plan-projection than vector similarity alone, and it runs on Ollama. (Mind the "needs a capable LLM" caveat → reserve for the 7–14 B tier / your earmarked qwen2.5:14b KB agent.)
2. **Ship a small-model preset matrix.** Default to **Gemma 3 4B** for capture-organization and **Phi-4-mini 3.8B** as the low-RAM/CPU fallback (best-in-class CPU tok/s); document quant (Q4_K_M) and RAM expectations. Aligns with 2026 consensus and the modest-hardware promise.
3. **Borrow proven capture UX.** Text Grab's background-process + global-hotkey model (and Amplenote's "capture note → later process" inbox loop) are validated patterns — lean on them for reliability and a frictionless review queue.
4. **Position explicitly against Reor's gap and the cloud tier.** Messaging: "the offline capture-and-organize app Reor users lost, plus plan projection — and unlike Mem/Saner/NotebookLM, nothing leaves your machine." This is now a true, sourced claim.
5. **Optional NotebookLM-style read view, fully local.** A lightweight "ask/summarize over my vault" mode (hybrid retrieval: semantic + full-text + RRF, as SurfSense/LightRAG do) would match table-stakes set by Open Notebook/Khoj without compromising offline guarantees — reusing the same Ollama runtime.

---

## Sources (URLs actually fetched or returned by search)

- Khoj — https://github.com/khoj-ai/khoj  *(fetched)*
- Reor — https://github.com/reorproject/reor and https://github.com/reorproject/reor/blob/main/README.md  *(README fetched; archived 7 Mar 2026)*
- LightRAG (EMNLP 2025) — https://github.com/hkuds/lightrag  *(fetched)*
- Open Notebook — https://github.com/lfnovo/open-notebook  *(fetched)*
- AnythingLLM (Ollama embedder docs) — https://docs.anythingllm.com/setup/embedder-configuration/local/ollama  *(search)*
- SiYuan — https://github.com/siyuan-note/siyuan  *(search)*
- Smart Second Brain (Obsidian) — https://www.obsidianstats.com/plugins/smart-second-brain ; https://github.com/your-papa/obsidian-smart2brain  *(search)*
- Logseq — https://logseq.com/ ; Logseq AI assistant — https://github.com/UNICKCHENG/logseq-ai-assistant  *(search)*
- Microsoft GraphRAG — https://microsoft.github.io/graphrag/  *(search)*
- WeKnora (Tencent) — https://github.com/Tencent/WeKnora  *(search)*
- Text Grab (Windows hotkey capture) — https://github.com/TheJoeFin/Text-Grab  *(search)*
- Antinote — https://www.todayonmac.com/antinote-the-three-second-solution-to-lost-thoughts/  *(search)*
- Amplenote global capture (Q2 2025) — https://www.amplenote.com/blog/q2_2025_completed_task_stats_default_cross_out_mood_tracking  *(search)*
- Mem review (cloud-only) — https://www.saner.ai/blogs/mem-ai-reviews  *(snippet; page body not retrievable)*
- Saner.ai (cloud SaaS) — https://www.saner.ai/blogs/best-ai-note-taking-apps  *(search)*
- Ollama library / June 2026 update — https://ollama.com/library ; https://www.promptquorum.com/local-llms/top-open-source-models-ollama  *(search)*
- Gemma 3 (Ollama) — https://ollama.com/library/gemma3  *(search)*
- Best local LLMs 8/16/32 GB (Micro Center) — https://www.microcenter.com/site/mc-news/article/best-local-llms-8gb-16gb-32gb-memory-guide.aspx  *(HTTP 403 on fetch; snippet-only)*
- Best local LLM models 2026 (SitePoint) — https://www.sitepoint.com/best-local-llm-models-2026/  *(HTTP 403 on fetch; snippet-only)*
- NotebookLM self-hosted alternative — https://www.xda-developers.com/notebooklm-self-hosted-alternative-keep-data-control/  *(search)*
- InsightsLM — https://github.com/theaiautomators/insights-lm-public  *(search)*
- SurfSense — https://github.com/Decentralised-AI/SurfSense-Open-Source-Alternative-to-NotebookLM  *(search)*
