# Slice A — Offline / Self-Hosted AI "Second Brain" Apps (RAG/Chat over your own notes)

Research for **grandplan** (native-Windows, fully-OFFLINE second brain: hotkey capture → local LLM organizes into atomic, lossless Markdown note → Obsidian vault + knowledge graph + plan).

**Non-negotiables grandplan must respect when borrowing:** offline-only (zero network egress at runtime), lossless verbatim preservation, local LLM only (Ollama), 16GB RAM / no-GPU, MIT-licensed → only MIT/Apache/BSD code is copyable; AGPL/GPL/source-available = **ideas only**.

All star counts and licenses verified via `gh api repos/<owner>/<name>` on **2026-06-19**. Stars rounded.

---

## License legend (code-copyability for an MIT project)

| License | Can copy code into grandplan? |
|---|---|
| MIT / Apache-2.0 / BSD-3 | **Yes** — permissive, attribution only |
| MPL / LGPL | Partial — file-level / dynamic-link copyleft, generally avoid copying |
| AGPL-3.0 / GPL-3.0 | **No** — copyleft incompatible with MIT distribution → ideas/architecture only |
| NOASSERTION / source-available (custom) | **No** — treat as ideas-only; check terms |

---

## Verified projects (16)

### 1. AnythingLLM — https://github.com/Mintplex-Labs/anything-llm
- **Stars:** ~61.8k · **License:** MIT (**code-copyable**) · active
- **Top techniques:**
  - **Workspaces** as isolated RAG containers (each with its own docs, vector namespace, system prompt, model) — clean multi-context isolation.
  - **Pluggable vector DB** (default LanceDB embedded; also PGVector, Chroma, Qdrant, Milvus, Weaviate). LanceDB = embedded, file-based, no server → fits offline desktop.
  - **"Native embedder"** ships a built-in embedding model so the app works with **zero external services** out of the box.
  - **Intelligent agent skill selection** — claims up to ~80% token reduction by only loading relevant tools; valuable for a 7B local model on 16GB RAM.
  - Source **citations** + drag-drop document collector service that parses PDF/DOCX/TXT.
- **Offline fit:** **Yes** — explicit local-first (Ollama, LM Studio, LocalAI, llama.cpp); LanceDB embedded.
- **Linking/identity:** doc-id within a workspace namespace (not name/path-stable across moves).
- **grandplan LACKS / worth borrowing:** the **embedded LanceDB + bundled native embedder** pattern (zero-dependency local vector search) and **token-frugal tool/skill selection** for small local models.

### 2. private-gpt (zylon-ai) — https://github.com/zylon-ai/private-gpt
- **Stars:** ~57.3k · **License:** Apache-2.0 (**code-copyable**) · active
- **Top techniques:**
  - Fully **air-gapped** pipeline reference (ingest → embed → store → query) with no egress; the canonical "100% private" design.
  - **Abstracted component layers** (LLM / embeddings / vector store / node store) swappable via config — good module boundaries (information hiding).
  - Local ingestion of many file types via an ingest service; supports bulk + watch-folder ingest.
  - API-first (FastAPI) with an OpenAI-compatible surface — useful contract pattern.
- **Offline fit:** **Yes** — designed for it (llama-cpp / Ollama, local embeddings).
- **Linking/identity:** doc-id + node-id in node store.
- **grandplan LACKS / worth borrowing:** clean **swappable-component abstraction** for embeddings/vector-store, and **watch-folder incremental ingest** (vault changes auto-reindexed).

### 3. khoj (khoj-ai) — https://github.com/khoj-ai/khoj
- **Stars:** ~35.2k · **License:** AGPL-3.0 (**ideas-only**) · active
- **Top techniques:**
  - **Incremental indexing** of Markdown/org/PDF/Notion — only changed files re-embedded (hash/mtime diff).
  - **Combined semantic + keyword** retrieval over personal notes.
  - **Links results back to source files** (jump to the note/heading) — strong "grounding in your own files" UX.
  - **Scheduled automations / deep-research agents** that run recurring queries over your corpus.
  - Native **Obsidian + Emacs** plugins (in-vault chat).
- **Offline fit:** **Yes** (any local LLM via Ollama/llama).
- **Linking/identity:** file-path + heading anchor back to the source note.
- **grandplan LACKS / worth borrowing (ideas-only):** **automations** (recurring research over the vault that surface new connections) and **path+heading-anchored citations** that open the exact note location.

### 4. quivr (QuivrHQ) — https://github.com/QuivrHQ/quivr
- **Stars:** ~39.2k · **License:** NOASSERTION / custom (**ideas-only**) · last push 2025-07 (stale)
- **Top techniques:**
  - **"Brains"** abstraction = isolated knowledge bases per topic (mirrors AnythingLLM workspaces).
  - Opinionated, embeddable RAG core meant to be dropped into other products (clean RAG SDK boundary).
  - Any-LLM / any-vectorstore (PGVector, FAISS) adapters.
- **Offline fit:** **Partial** — supports local (Llama, FAISS, PGVector) but historically cloud/Supabase-leaning; verify no egress.
- **grandplan LACKS / worth borrowing:** the **RAG-core-as-a-library** packaging discipline (ideas-only due to license).

### 5. onyx / danswer (onyx-dot-app) — https://github.com/onyx-dot-app/onyx
- **Stars:** ~30.4k · **License:** NOASSERTION (mixed; MIT + Enterprise) (**ideas-only / verify per-file**) · active
- **Top techniques:**
  - **Hybrid retrieval** (BM25 keyword + dense vectors) with a **reranking** stage — high-recall + high-precision combo.
  - **Connectors framework** (40+ sources) with **incremental sync + permission-aware** indexing.
  - Inline **citations** tied to source chunks.
- **Offline fit:** **Partial** — self-hostable with local models, but heavy stack (Vespa, Postgres); not laptop-light.
- **grandplan LACKS / worth borrowing:** **hybrid (BM25+vector) + rerank** is the single most impactful retrieval-quality upgrade (architecture is the takeaway; license/weight make code unsuitable).

### 6. Verba (weaviate) — https://github.com/weaviate/Verba
- **Stars:** ~7.7k · **License:** BSD-3-Clause (**code-copyable**) · **ARCHIVED**
- **Top techniques:**
  - Clean **modular RAG pipeline** with **swappable stages** (Reader → Chunker → Embedder → Retriever → Generator) — textbook strategy-pattern pipeline.
  - Multiple **chunking strategies** exposed as plug-ins (token, sentence, semantic).
  - **Hybrid search** + window-based context expansion around the matched chunk.
- **Offline fit:** **Partial** (Ollama supported; built around Weaviate).
- **grandplan LACKS / worth borrowing:** the **explicit pluggable chunking-strategy interface** and **context-window expansion** (return neighbor chunks around a hit). BSD = copyable, but archived (no maintenance).

### 7. localGPT (PromtEngineer) — https://github.com/PromtEngineer/localGPT
- **Stars:** ~22.2k · **License:** MIT (**code-copyable**) · active
- **Top techniques:**
  - **100% offline** ingest→ask reference loop; explicitly "no data leaves your device."
  - GPU-optional / CPU-friendly local embeddings + GGUF models — relevant to 16GB no-GPU.
  - Simple, readable end-to-end pipeline (good to port).
- **Offline fit:** **Yes** (designed offline; llama-cpp, local embeddings).
- **grandplan LACKS / worth borrowing:** a minimal **CPU-only embedding + GGUF** reference config tuned for low RAM (copyable).

### 8. kotaemon (Cinnamon) — https://github.com/Cinnamon/kotaemon
- **Stars:** ~25.5k · **License:** Apache-2.0 (**code-copyable**) · active
- **Top techniques:**
  - **Hybrid (full-text + vector) retriever + reranking** as the sane default pipeline.
  - **Detailed citations with relevance scores** AND a **low-relevance warning** when retrieval is weak — directly fights hallucination/over-confidence.
  - **Multiple GraphRAG backends** pluggable (nano-graphrag, LightRAG, MS GraphRAG).
  - **Multimodal parsing** (figures/tables/OCR).
- **Offline fit:** **Yes** (Ollama / GGUF via llama-cpp-python; Docker image bundles Ollama).
- **grandplan LACKS / worth borrowing:** **citations + a "low retrieval confidence" warning** — a fail-loud signal that pairs perfectly with grandplan's fail-loud philosophy. Apache → copyable.

### 9. RAGFlow (infiniflow) — https://github.com/infiniflow/ragflow
- **Stars:** ~83.2k · **License:** Apache-2.0 (**code-copyable**) · active
- **Top techniques:**
  - **Deep document understanding** — layout-aware parsing of complex docs (tables, headers, structure) before chunking → far better chunk boundaries.
  - **Template-based chunking** per document type.
  - **Chunk-level grounded citations** ("traceable" answers) to reduce hallucination.
  - Self-RAG / re-ranking patterns.
- **Offline fit:** **Partial** — supports local models but heavyweight (Elasticsearch/Infinity, MinIO, deep-learning parsers); not 16GB-friendly as-is.
- **grandplan LACKS / worth borrowing:** **layout/structure-aware chunking** ideas (grandplan's notes are clean Markdown so this is lower-priority, but the *template-per-type chunking* idea maps to note-type-aware atomization).

### 10. open-webui — https://github.com/open-webui/open-webui
- **Stars:** ~142.3k · **License:** NOASSERTION (custom, source-available; branding-restricted) (**ideas-only**) · active
- **Top techniques:**
  - First-class **Ollama** integration + built-in **document/RAG** ("#" to reference a doc inline in chat).
  - **Hybrid search + reranking** in its RAG settings; per-model knowledge "collections."
  - **Citations** inline; offline PWA.
- **Offline fit:** **Yes** (Ollama-native, runs fully local).
- **grandplan LACKS / worth borrowing (ideas-only):** the **`#`-mention-a-note inline** UX to inject a specific note as grounded context into a chat turn.

### 11. cognita (truefoundry) — https://github.com/truefoundry/cognita
- **Stars:** ~4.4k · **License:** Apache-2.0 (**code-copyable**) · **ARCHIVED**
- **Top techniques:**
  - **Modular, config-driven RAG** where every component (parser, embedder, retriever, reranker) is a registered, swappable module — production-grade extensibility pattern.
  - Incremental indexing with metadata store.
- **Offline fit:** **Partial** (local-model capable; container-oriented).
- **grandplan LACKS / worth borrowing:** the **component-registry pattern** for RAG stages (good architecture; Apache copyable but unmaintained).

### 12. karakeep (was Hoarder) — https://github.com/karakeep-app/karakeep
- **Stars:** ~26.1k · **License:** AGPL-3.0 (**ideas-only**) · active
- **Top techniques:**
  - **Local-LLM auto-tagging** of saved items (Ollama) — automatic taxonomy generation.
  - **Full-text + semantic** search over a personal bookmark/note hoard.
  - Background **content extraction** + on-device processing.
- **Offline fit:** **Yes** (Ollama for tagging/inference).
- **grandplan LACKS / worth borrowing (ideas-only):** **LLM auto-tagging at capture time** to enrich each atomic note's metadata for later retrieval/graph edges.

### 13. Reor (reorproject) — https://github.com/reorproject/reor
- **Stars:** ~8.6k · **License:** AGPL-3.0 (**ideas-only**) · **ARCHIVED**
- **Top techniques:**
  - **Auto-linking notes by vector similarity** — every note is chunked+embedded; related notes appear automatically (no manual `[[links]]`). This is the closest architectural sibling to grandplan's knowledge-graph goal.
  - **Per-note RAG sidebar**: while editing, related chunks are retrieved and shown (and feed Q&A).
  - Stack: **Ollama + Transformers.js (in-app embeddings) + LanceDB (embedded)** — a complete offline desktop RAG with no server.
- **Offline fit:** **Yes** (fully local by design).
- **Linking/identity:** **semantic vector similarity**, NOT id/path — automatic edges.
- **grandplan LACKS / worth borrowing (ideas-only, but very high value):** **automatic similarity-based note linking** to augment the explicit graph — surface "related notes" grandplan never linked manually. (AGPL → reimplement, don't copy.)

### 14. Notesnook (streetwriters) — https://github.com/streetwriters/notesnook
- **Stars:** ~14.2k · **License:** GPL-3.0 (**ideas-only**) · active
- **Top techniques:**
  - **End-to-end encryption** + local-first storage (privacy-by-architecture).
  - Offline-first sync/conflict model.
- **Offline fit:** **Yes** (local-first) — but it's a note app, **not RAG-focused**; included as a privacy/storage reference only.
- **grandplan LACKS / worth borrowing (ideas-only):** at-rest **encryption** patterns (grandplan is plaintext vault by design, so low priority).

### 15. SurfSense (MODSetter) — https://github.com/MODSetter/SurfSense
- **Stars:** ~15.0k · **License:** Apache-2.0 (**code-copyable**) · active
- **Top techniques:**
  - **2-tier / hierarchical RAG** (retrieve at document level, then drill into chunks) — better precision than flat single-tier retrieval.
  - **Cited, grounded answers** ("NotebookLM + Perplexity" style).
  - Pluggable local embeddings + Ollama; many connectors.
- **Offline fit:** **Partial → Yes** (local models supported; verify connectors don't egress).
- **grandplan LACKS / worth borrowing:** **hierarchical 2-tier retrieval** (note-level coarse filter → chunk-level fine retrieval) — scalable + precise; Apache → copyable.

### 16. LightRAG (HKUDS) — https://github.com/HKUDS/LightRAG
- **Stars:** ~36.8k · **License:** MIT (**code-copyable**) · active
- **Top techniques:**
  - **Graph-based RAG**: LLM extracts **entities + relations** to build a knowledge graph, then retrieves over graph structure (not just chunk similarity).
  - **Dual-level retrieval**: **local** (precise entity/fact matching) + **global** (macro themes / cross-document relationships) — answers both "what is X" and "how do these ideas connect."
  - **Incremental KG updates via set-merge** of per-document local graphs — new notes merge without full rebuild; **deletion supported** via cached extractions (mirrors grandplan's tombstone/incremental needs).
  - Far **lighter than MS GraphRAG** (no community-report generation / fewer LLM calls) — important for a 7B local model on 16GB.
  - **Offline deployment guide** for air-gapped (local embed + rerank + storage).
- **Offline fit:** **Yes** (explicit air-gapped support).
- **Linking/identity:** **entity nodes + typed relations** (entity-name keyed, deduped via LLM merge).
- **grandplan LACKS / worth borrowing (HIGH value, MIT copyable):** **LLM entity+relation extraction → graph-structured retrieval with incremental merge/delete.** This is the strongest match for grandplan's "knowledge graph + context-aware reconcile" roadmap, and its **incremental-merge + deletion** model aligns with grandplan's event-sourced/tombstone design.

#### Honorable mentions (verified, niche)
- **nano-graphrag** (gusye1234) — ~3.9k ⭐, **MIT** (copyable): a ~1k-LOC, hackable GraphRAG implementation — ideal **readable reference** to port graph extraction without the heavy MS GraphRAG dependency. Offline-capable with local LLM.
- **GraphRAG-Local-UI** (severian42) — ~2.3k ⭐, **MIT** (copyable): wires MS GraphRAG to **local LLMs** (Ollama) end-to-end; a working offline GraphRAG reference.
- **Open Notebook** (lfnovo) — ~31.8k ⭐, **MIT** (copyable): NotebookLM-style; podcast/audio-overview generation + source grounding; local via Ollama.
- **MCP-Markdown-RAG** (Zackriya-Solutions) — small, **Apache-2.0**: semantic search over Markdown exposed as an **MCP server** with local Milvus — directly relevant to grandplan's existing MCP server (agent-vault read API).

---

## Synthesis — Top 5 techniques grandplan should borrow

Ranked by value × offline-safety × fit with grandplan's existing event-sourced/graph/reconcile roadmap.

| # | Technique | Source repo | License | Offline-safe? | Rough effort |
|---|---|---|---|---|---|
| 1 | **Hybrid retrieval (BM25/full-text + dense vectors) + a reranking stage**, with a **low-confidence "warning" signal** when top results are weak | kotaemon (pattern); onyx (pattern) | **Apache-2.0** (kotaemon, copyable); onyx ideas-only | **Yes** — BM25 + local embeddings + local cross-encoder rerank all run on CPU | **Medium.** Add an embedding index over note chunks + a keyword index, fuse scores (RRF), optional small local reranker. The fail-loud "low retrieval confidence" warning is cheap and matches grandplan's philosophy. |
| 2 | **LLM entity + relation extraction → graph-structured retrieval with incremental merge & delete** (dual-level: local entity facts + global cross-note themes) | LightRAG | **MIT (copyable)**; nano-graphrag (MIT) as readable port reference | **Yes** — explicit air-gapped guide; lighter than MS GraphRAG (fits 7B/16GB) | **High.** But it is the deepest fit for grandplan's knowledge-graph + context-aware-reconcile direction; its **incremental-merge + tombstone-style deletion** maps onto grandplan's event-sourced substrate. Stage it (extraction → graph store → dual retrieval). |
| 3 | **Automatic similarity-based note linking** ("related notes" surfaced by vector similarity, augmenting the explicit graph) | Reor (architecture) | AGPL → **ideas-only, reimplement** | **Yes** — Transformers.js/local embeddings + embedded LanceDB, no server | **Medium.** Reuse the chunk embeddings from #1; compute top-k neighbors per note → suggested edges grandplan never linked manually. Strong UX win, low marginal cost once embeddings exist. |
| 4 | **Embedded, file-based vector store (LanceDB) + bundled native embedder** = zero-dependency, fully-offline semantic search | AnythingLLM; Reor; localGPT | **MIT (copyable)** | **Yes** — embedded DB, no server process; CPU embeddings | **Low–Medium.** LanceDB is embedded (no server, no egress), aligns with grandplan's no-network constraint and 16GB budget. Foundation that #1/#3 build on. |
| 5 | **Watch-folder incremental indexing + LLM auto-tagging at capture** (only changed notes re-embedded; each note auto-enriched with tags/metadata for retrieval & graph edges) | private-gpt / khoj (incremental); karakeep (auto-tagging) | private-gpt **Apache (copyable)**; khoj/karakeep AGPL → **ideas-only** | **Yes** — hash/mtime diff + local LLM tagging via Ollama | **Low–Medium.** grandplan already writes notes on capture; hook an incremental embed + a single local-LLM tagging pass per new/changed note. Keeps the index fresh without full rebuilds (mirrors grandplan's projection/reconcile model). |

### Cross-cutting notes for grandplan
- **Note identity / linking:** the strongest offline systems link by **semantic vector similarity** (Reor) or **extracted entity nodes** (LightRAG), *in addition to* path/id. grandplan already uses explicit graph edges + body-ownership; adding **similarity-derived "soft" edges** and **entity nodes** would materially increase graph fidelity without manual linking.
- **Grounding / fail-loud:** kotaemon's **citations + low-relevance warning** and RAGFlow's **chunk-traceable answers** both reinforce grandplan's lossless + fail-loud non-negotiables — every generated/reconciled statement should cite the source note chunk, and weak retrieval should warn rather than confabulate.
- **Weight/RAM:** prefer the **LanceDB + CPU-embeddings + GGUF** class (AnythingLLM, Reor, localGPT) over heavyweight stacks (RAGFlow=Elasticsearch, onyx=Vespa) — those won't fit 16GB no-GPU.
- **License discipline:** the two highest-leverage *copyable* sources are **LightRAG (MIT)** for graph RAG and **kotaemon (Apache)** for hybrid+rerank+citations. Khoj, Reor, karakeep, quivr, onyx, open-webui are **ideas-only** (AGPL/GPL/source-available) — reimplement, never copy.
