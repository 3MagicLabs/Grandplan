# D — AI Memory Layers, Knowledge-Graph Construction & Retrieval Techniques

> Research slice **D**: the engine room — memory layers, KG construction, entity/relation
> extraction, and retrieval techniques that grandplan can borrow.
> Scope is **libraries & techniques only** — not end-user note apps or task/planning UIs.
>
> **Date:** 2026-06-19 · **Method:** read-only research (WebSearch / WebFetch / `gh api`).
> All star counts and SPDX licenses verified live via the GitHub API on the date above.
> **Constraints carried throughout:** grandplan is fully **offline**, **lossless**,
> **local-LLM**, **16GB RAM / no GPU**, **MIT**.

---

## 0. grandplan today (the baseline these are measured against)

Verified by reading the repo (`src/grandplan/core/`, `src/grandplan/adapters/`, ADRs):

| Capability | Current state | Gap |
|---|---|---|
| Embeddings | **Note-level only.** `HashingEmbedder` (feature-hashing, dependency-free baseline) + optional sentence-transformers behind the `Embedder` port. | No **chunk/block-level** embeddings. |
| Graph | Typed edges (`Edge.kind`) projected to `graph.json`; same node/edge model feeds doc, graph view, plan (ADR-0004). Edges produced by **LLM reconciliation**, not extraction. | No **entity/relation extraction**; no **entities** as first-class nodes. |
| Retrieval | `LlmContextualReconciler` does **"whole-neighborhood RAG"** — feeds the LLM the surrounding neighborhood. | **Context bottleneck** as the vault grows to thousands of notes. |
| Maintenance | Reconcile proposes status changes to existing notes; tombstones for deletes (PR #63/#65). | No **incremental graph maintenance**, no **entity/fact dedup/merge**, no **conflict resolution / bi-temporal** model. |
| Hybrid / rerank | None. | No **BM25 + vector fusion**, no **re-ranking**, no **community/global** retrieval. |

**The five concrete gaps to close (per the brief):**
1. chunk/block-level embeddings
2. entity/relation extraction to *build* the graph
3. GraphRAG-style retrieval (local/global/community)
4. incremental graph maintenance + dedup/merge + conflict resolution
5. scaling retrieval to thousands of notes **without** a context bottleneck

> **License lens.** A striking finding: **every library surveyed is MIT or Apache-2.0** —
> i.e. **code is copyable/portable**, none is AGPL/GPL "ideas-only". So the constraint is
> not licensing; it is offline-fit on 16GB/no-GPU and engineering effort.

---

## 1. GraphRAG family (build-a-graph-from-text + community retrieval)

| Library | Stars | License | Offline-fit |
|---|---:|---|---|
| Microsoft GraphRAG | 33,867 | MIT | yes (LLM-call-heavy at index) |
| LightRAG | 36,781 | MIT | yes |
| R2R | 7,891 | MIT | partial (heavy in full mode) |
| nano-graphrag | 3,889 | MIT | yes (lightest, hackable) |
| fast-graphrag (circlemind) | 3,804 | MIT | yes |

### 1.1 Microsoft GraphRAG — `microsoft/graphrag`
- **33,867** stars · **MIT** · https://github.com/microsoft/graphrag
- **Techniques:** (1) LLM entity+relationship extraction into a typed KG with per-node/edge
  descriptions; (2) **hierarchical Leiden community detection** (nested communities); (3)
  **community-report summarization** at each level; (4) three query modes — *Local* (entity
  neighborhood), *Global* (map-reduce over community reports for corpus-wide questions),
  **DRIFT** (global seeding + local follow-up); (5) **incremental indexing** (v0.4+
  `get_delta_docs` diffs new/deleted docs, no full rebuild).
- **Offline:** runs against any OpenAI-compatible endpoint → point `api_base` at Ollama
  (`localhost:11434/v1`), local embed model (`nomic-embed-text`), local LanceDB + Parquet
  artifacts. Caveat: extraction + per-community summaries are **very LLM-call-heavy** → slow on
  CPU-only 16GB.
- **grandplan lacks:** the whole build-a-graph path, **community detection + community reports**,
  and **global/community retrieval** — the mechanism that answers corpus-wide questions
  *without* stuffing every note into context.

### 1.2 LightRAG — `HKUDS/LightRAG`
- **36,781** stars (most-starred in the set) · **MIT** · https://github.com/HKUDS/LightRAG
- **Techniques:** (1) entity/relation extraction (optional JSON-structured output for
  stability); (2) **dual-level retrieval** — *low-level* (specific entities/attributes) +
  *high-level* (themes / cross-document) run together; (3) **hybrid graph + vector** retrieval;
  (4) **incremental graph set-merge** (new subgraph merged into the global graph, no full
  reindex); (5) **entity dedup/merge** with source-ID caps to bound description growth.
- **Offline:** default local file-persisted storage (NetworkX graph + nano-vectordb-style
  vectors); OpenAI-compatible path covers Ollama; self-hostable backends (Postgres/Neo4j/
  Milvus/Qdrant). Lighter than MS GraphRAG (skips full community-report generation).
- **grandplan lacks:** the **dual-level (low/high) retrieval split** — pinpoint *and* thematic
  recall *without* community-detection indexing cost; plus incremental set-merge and dedup.

### 1.3 nano-graphrag — `gusye1234/nano-graphrag`
- **3,889** stars · **MIT** · https://github.com/gusye1234/nano-graphrag
- A clean **~1.1k-LOC reference implementation** of MS GraphRAG — ideal to *read and port*
  (last push 2026-01-27; least actively maintained, but that matters less for a port target).
- **Techniques:** entity/relation extraction; **Leiden community detection + community
  reports**; **local & global** query modes; **incremental insert with dedup** (MD5
  content-hash chunk keys; entities merged/deduped across insertions); pluggable storage.
- **Offline:** Ollama + sentence-transformers examples; **NetworkX** graph (in-memory),
  nano-vectordb / hnswlib / Milvus-Lite vectors — all local. Lightest footprint of the family.
- **grandplan lacks:** same as MS GraphRAG but in a tiny hackable form, **plus** an explicit
  copyable **entity dedup/merge** routine (grandplan has none).

### 1.4 R2R — `SciPhi-AI/R2R`
- **7,891** stars · **MIT** · https://github.com/SciPhi-AI/R2R (last push 2025-11-07)
- **Techniques:** (1) automatic entity/relation extraction — their **Triplex** model
  (Phi-3-3.8B fine-tune for S-P-O triplets) runs locally via Ollama (`sciphi/triplex`); (2)
  GraphRAG with **Leiden community detection** + graph enrichment; (3) **hybrid search** —
  semantic + full-text fused via **reciprocal rank fusion (RRF)**; (4) **agentic RAG** +
  "Deep Research" multi-step API; (5) full ingestion pipeline + REST API.
- **Offline:** **partial.** Local LLM + local Postgres/pgvector ("light mode") fits 16GB; but
  "full mode" GraphRAG clustering pulls in **Hatchet + Unstructured** via Docker Compose —
  heavier, more operationally complex. It's a **production service**, not a library.
- **grandplan lacks:** **RRF hybrid search** (cheap, high-leverage) and **Triplex** as a
  concrete local entity-extraction model.

### 1.5 fast-graphrag (circlemind) — `circlemind-ai/fast-graphrag`
- **3,804** stars · **MIT** · https://github.com/circlemind-ai/fast-graphrag (last push 2025-11-01)
- **Techniques:** (1) **domain-adaptive extraction** (you supply entity types + a domain
  prompt); (2) interpretable, queryable/visualizable/updatable KG; (3) **Personalized
  PageRank retrieval** — seed from query-relevant entities, walk the graph to rank the most
  relevant info (its signature, vs Leiden-community approaches); (4) **real-time incremental
  updates** without reprocessing; (5) persistent local `working_dir`.
- **Offline:** any OpenAI-API-compatible LLM + embedder (Ollama/llama.cpp);
  `CONCURRENT_TASK_LIMIT` to throttle for constrained local models; fully offline after build.
- **grandplan lacks:** **Personalized-PageRank graph retrieval** — a lightweight rank-and-walk
  from query-relevant seeds that scales to thousands of notes *without* stuffing the
  neighborhood into the LLM (directly attacks the context bottleneck), plus domain-typed extraction.

---

## 2. Agent-memory / KG-memory family (extraction + dedup + conflict resolution)

| Library | Stars | License | Offline-fit |
|---|---:|---|---|
| mem0 | 58,940 | Apache-2.0 | yes (configure local embedder) |
| graphiti | 27,631 | Apache-2.0 | yes (needs JSON-capable model) |
| supermemory | 27,205 | MIT | yes (local-first OSS binary) |
| Letta / MemGPT | 23,416 | Apache-2.0 | partial (fragile on small models) |
| cognee | 17,910 | Apache-2.0 | yes (wants 32B+ for quality) |
| Memary | 2,624 | MIT | yes (but ~unmaintained) |

### 2.1 mem0 — `mem0ai/mem0`
- **58,940** stars · **Apache-2.0** · https://github.com/mem0ai/mem0
- **Techniques:** (1) **LLM memory operations ADD / UPDATE / DELETE / NOOP** — each candidate
  fact classified against the *retrieved* neighborhood (ADD if no equivalent, UPDATE to
  augment, DELETE on contradiction, NOOP otherwise) — the canonical two-phase
  extract-then-update pipeline; (2) **fact extraction → cosine-similarity dedup** before
  deciding the op (explicit fact-level dedup); (3) graph variant (mem0-graph): **conflict
  detection + LLM resolver** marks conflicting relations invalid without deleting; entity +
  relation triplets extracted; (4) newer fast path: single-pass ADD-only with entity linking +
  multi-signal retrieval (semantic + BM25 + entity).
- **Offline:** **yes** — Ollama LLMs (tool-calling) + **Ollama embeddings** for fully-local
  embedding; local vector stores (Qdrant/Chroma). Caveat: default examples use an OpenAI
  embedder key — must explicitly configure the Ollama embedder to be truly offline.
- **grandplan lacks:** **fact/entity-granularity** dedup + the **ADD/UPDATE/DELETE/NOOP**
  classification *against k-nearest facts* (never the whole neighborhood) — fixes dedup AND the
  context bottleneck at once.

### 2.2 graphiti — `getzep/graphiti`
- **27,631** stars · **Apache-2.0** · https://github.com/getzep/graphiti
- **Techniques (most relevant to grandplan):** (1) **bi-temporal KG** — every fact carries
  validity windows with **automatic fact invalidation** (old facts invalidated, *not* deleted);
  (2) **incremental, real-time graph maintenance** — new episodes integrate immediately, **no
  batch recomputation**; (3) entity/edge extraction via **structured JSON output** + **node/edge
  dedup & resolution** in the ingestion pipeline; (4) **conflict resolution via edge
  invalidation** rather than overwrite (preserves history); (5) **episodic vs semantic**
  separation with provenance to source episodes.
- **Offline:** **yes** — any OpenAI-compatible `/v1` endpoint (Ollama/vLLM/llama.cpp/LM Studio);
  local graph store Neo4j or FalkorDB. Caveat: extraction *requires* reliable JSON output →
  pick a tool/JSON-capable local model.
- **grandplan lacks:** **bi-temporal incremental maintenance with edge invalidation** — the
  principled generalization of grandplan's primitive "reconcile proposes status changes".

### 2.3 supermemory — `supermemoryai/supermemory`
- **27,205** stars · **MIT** · https://github.com/supermemoryai/supermemory
- **Techniques:** (1) memory/context engine that extracts facts + **handles temporal changes +
  contradictions** automatically; (2) entity extraction + dual profile (static facts + dynamic
  context); (3) KG + ontology, **dedup & contradiction resolution**, **hybrid retrieval**
  (document RAG + personalized memory in one query).
- **Offline:** **yes** — README: "Fully offline if you want — point it at Ollama and nothing
  leaves your machine," data in `./.supermemory`, local server `:6767`. Caveat: a hosted SaaS
  tier exists; verify which extraction features are local-only vs gated before depending.
- **grandplan lacks:** local-first **contradiction resolution** in a single binary; ideas-only
  given hosted-tier ambiguity.

### 2.4 Letta / MemGPT — `letta-ai/letta`
- **23,416** stars · **Apache-2.0** · https://github.com/letta-ai/letta
- **Techniques:** (1) **self-editing memory** — the agent edits its own memory via tool calls
  (`core_memory_append`, `core_memory_replace`) inside its reasoning loop; (2) **OS-inspired
  three-tier memory** — Core (in-context "RAM"), Recall (searchable history "disk cache"),
  Archival (vector store "cold storage"); (3) **virtual context management / paging** —
  summarize + page when the window fills.
- **Offline:** **partial → yes with caveats.** Ollama supported, but Letta is *heavily*
  tool-calling-dependent; docs warn against quantization below Q5 and recommend native-tool-use
  models. Small quantized local models often fail the self-editing loop — **weakest offline fit
  on constrained hardware** in the Apache group.
- **grandplan lacks:** the **tiered memory + paging** idea (bounding in-context size) — useful
  conceptually, risky to depend on at 16GB.

### 2.5 cognee — `topoteretes/cognee`
- **17,910** stars · **Apache-2.0** · https://github.com/topoteretes/cognee
- **Techniques:** (1) **ECL pipeline** (Extract → Cognify → Load): docs → LLM
  entity/relationship/concept extraction → KG + vector embeddings; (2) **ontology grounding** +
  dedup during construction; (3) dual store (meaning + relationships); evolving graph
  (`remember`/`recall`/`forget`/`improve`).
- **Offline:** **yes (fully)** — SQLite + LanceDB + Kuzu/NetworkX + Ollama `/v1` for LLM &
  embeddings. Caveat: graph quality leans on **32B+** models; small models degrade extraction —
  a real risk on 16GB/no-GPU.
- **grandplan lacks:** ontology-grounded extraction; but the 32B+ expectation is a poor fit for
  the hardware envelope (ideas-only here).

### 2.6 Memary — `kingjulio8238/Memary`
- **2,624** stars · **MIT** · https://github.com/kingjulio8238/Memary
- **Techniques:** (1) **Memory Stream** — every entity inserted with a timestamp (episodic);
  (2) **Entity Knowledge Store** — per-entity **frequency + recency** metrics (semantic-ish);
  (3) **recency+frequency ranking → top-N entity selection** injected into context (a concrete
  answer to the context bottleneck); (4) Neo4j KG + recursive multi-hop retrieval.
- **Offline:** **yes by default** ("defaults to locally run models"). **Major caveat: ~unmaintained**
  (last push 2024-10-22, smallest community) → **ideas-only**.
- **grandplan lacks:** **frequency+recency entity ranking → top-N injection** — a tiny, copyable
  idea that bounds context size regardless of vault size.

---

## 3. RAG-framework / KG-extraction / local-embedding family (chunking, hybrid, rerank)

| Library | Stars | License | Offline-fit |
|---|---:|---|---|
| LlamaIndex | 50,228 | MIT | yes |
| Haystack | 25,614 | Apache-2.0 | yes |
| llmware | 14,833 | Apache-2.0 | yes (strongest offline story) |
| txtai | 12,669 | Apache-2.0 | yes |
| EmbedChain (in mem0 repo) | 58,941 (repo) | Apache-2.0 | yes |
| Langroid | 4,040 | MIT | yes |

### 3.1 LlamaIndex — Property Graph Index — `run-llama/llama_index`
- **50,228** stars · **MIT** · https://github.com/run-llama/llama_index
- **Techniques:** (1) **schema-guided property-graph extraction** — `SchemaLLMPathExtractor`
  enforces a Pydantic schema (allowed entity types + allowed relations), validating each
  `(entity, relation, entity)` path; `DynamicLLMPathExtractor` (constrained types, free labels);
  `SimpleLLMPathExtractor` (unconstrained); `ImplicitPathExtractor` (reuse existing relationships,
  no LLM cost); (2) **chunk-level + graph hybrid retrieval** — `VectorContextRetriever` (vector
  over graph nodes/chunks with path-depth traversal) + `LLMSynonymRetriever` (keyword/synonym
  expansion) + `TextToCypherRetriever`; (3) **chunk-level embeddings** first-class (nodes =
  chunks); (4) **re-ranking** via postprocessors incl. local cross-encoder `SentenceTransformerRerank`;
  (5) storage `SimplePropertyGraphStore` (in-memory, disk-persistent — no external DB).
- **Offline:** **yes** — Ollama + HF/sentence-transformers + `SimplePropertyGraphStore` + local
  vector store.
- **grandplan lacks:** **schema-guided, per-path-validated extraction** (the highest-fidelity
  way to upgrade typed edges) + multi-retriever hybrid + chunk-level embeddings.

### 3.2 Haystack — `deepset-ai/haystack`
- **25,614** stars · **Apache-2.0** · https://github.com/deepset-ai/haystack
- **Techniques:** (1) composable **pipeline/component** architecture; (2) `DocumentSplitter`
  (chunk by word/sentence/passage with overlap); (3) **hybrid retrieval** —
  `InMemoryBM25Retriever` + `InMemoryEmbeddingRetriever` joined via `DocumentJoiner` (RRF/merge);
  (4) **re-ranking** — `TransformersSimilarityRanker` (local cross-encoder), DiversityRanker,
  `LostInTheMiddleRanker`; (5) chunk-level embeddings default; query decomposition via branching.
- **Offline:** **yes** — `OllamaGenerator`/`LlamaCppGenerator` + `SentenceTransformersTextEmbedder`
  + `InMemoryDocumentStore`.
- **grandplan lacks:** clean **splitter → retriever → ranker** hybrid pipeline w/ local
  cross-encoder rerank + RRF fusion.

### 3.3 llmware — `llmware-ai/llmware`
- **14,833** stars · **Apache-2.0** · https://github.com/llmware-ai/llmware
- **Techniques:** (1) **Parse → Text Chunk → Embed** core workflow (chunk-level embeddings,
  configurable batch); (2) **dual-pass / hybrid retrieval** (semantic + keyword filter); (3)
  **SLIM small-specialist models** for `extract` and **NER / entity extraction** (function-calling
  small models); (4) **reranker** models via ONNXRuntime / OpenVINO (local); (5) explicitly
  built for **local/edge** — GGUF/OpenVINO/ONNX, 300+ model catalog (BLING/DRAGON/SLIM).
  Caveat: the dedicated **Graph module was removed/deprecated** → no built-in KG, only SLIM extraction.
- **Offline:** **yes — strongest "designed-for-offline" story.** CPU-only GGUF fits 16GB/no-GPU.
- **grandplan lacks:** chunk embeddings + local reranker; **CPU-optimized small extraction models
  (SLIM NER)** sized for the hardware envelope; dual-pass hybrid.

### 3.4 txtai — `neuml/txtai`
- **12,669** stars · **Apache-2.0** · https://github.com/neuml/txtai
- **Techniques:** (1) **true hybrid index** — enabling hybrid creates a **BM25 index** alongside
  the dense vector index (sparse + dense fused); (2) embeddings DB = union of vector indexes +
  graph networks + relational DB in one store; (3) **semantic graph** — edges auto-created from
  the embeddings index (**similarity-derived**, *not* schema extraction) + community detection /
  topic modeling (Louvain); (4) **segmentation** (chunking) + a **Reranker** pipeline; (5) local
  sentence-transformers via local model paths.
- **Offline:** **yes** — local ST models + BM25 + NetworkX graph.
- **grandplan lacks:** hybrid sparse+dense out of the box + chunked embeddings + similarity-graph
  / topic-modeling. **Caveat:** its graph is similarity-only — grandplan's *typed* LLM edges are
  richer; borrow txtai's **retrieval**, not its graph builder.

### 3.5 EmbedChain (now under `mem0ai/mem0`, `/embedchain`)
- **58,941** stars (whole mem0 repo) · **Apache-2.0** · https://github.com/mem0ai/mem0
- **Techniques:** (1) **EmbedChain:** `ChunkerConfig` (chunk_size / overlap) → chunk-level
  embeddings → local Chroma (persistent `./db`); local embedders (HF/ST/GPT4All) + local LLMs
  (Ollama/GPT4All/llama.cpp); RAG-only, **no schema-guided graph**; (2) **mem0 graph memory:**
  builds its own graph, extracts entities (proper nouns, quoted text, compound nouns) into a
  parallel collection; retrieval = **multi-signal hybrid** (semantic + BM25 + entity-graph
  boost) with **graceful degradation** if spaCy is absent. **Pattern-based, NOT schema-guided.**
- **Offline:** **yes** for embedchain RAG and mem0 graph memory (no external Neo4j since rewrite).
- **grandplan lacks:** chunking config (embedchain); hybrid vector+BM25+entity-boost ranker with
  degradation fallback (mem0). Its extraction is weaker than schema-guided.

### 3.6 Langroid — `langroid/langroid`
- **4,040** stars · **MIT** · https://github.com/langroid/langroid
- **Techniques:** (1) **`DocChatAgent` — a best-in-class hybrid retrieval reference:** dense
  vector + **BM25 lexical** + **fuzzy** matching fused via **RRF**, then **cross-encoder
  re-ranking**, plus **relevance extraction** (LLM extracts only the relevant *sentences* from
  retrieved chunks — cuts context bloat); (2) configurable chunking + chunk embeddings;
  Qdrant/Chroma/LanceDB local; (3) Neo4j KG integration + query-planning/critic agents.
- **Offline:** **yes** — Ollama (`OLLAMA_BASE_URL`) + local ST embeddings + local vector store;
  cross-encoder reranker runs locally.
- **grandplan lacks:** the full **vector + BM25 + fuzzy → RRF → cross-encoder rerank →
  relevance-extraction** pipeline — and **relevance-extraction** directly trims retrieved chunks
  before they hit the LLM (attacks the context bottleneck).

---

## 4. Synthesis — top 5 techniques grandplan should borrow

Prioritized for **better auto-linking** and **scaling without a context bottleneck**, weighted
for the 16GB/no-GPU/offline envelope. Effort = rough implementation cost behind grandplan's
existing ports (`Embedder`, `NoteRepository`).

### #1 — Chunk/block-level embeddings (precondition for everything else)
- **Why:** grandplan is alone in embedding at *note* granularity; every RAG library embeds the
  *chunk*. Block-level embeddings are the precondition for precise retrieval, hybrid search, and
  re-ranking. grandplan's lossless atomic-note model already maps naturally to blocks.
- **Source:** Haystack `DocumentSplitter`, llmware "Parse→Chunk→Embed", embedchain `ChunkerConfig`
  (~400–512 tokens, 10–20% overlap). **License:** Apache-2.0 / Apache-2.0.
- **Offline-safe:** **yes** — grandplan's sentence-transformers path already runs locally; only
  the chunker + parent/child (block→note) mapping is new.
- **Effort:** **Low–Medium.** New `Chunker` + extend the `Embedder` port to block IDs.

### #2 — Hybrid retrieval + local re-ranking + relevance-extraction (the context-bottleneck fix)
- **Why:** the single most direct attack on the "whole-neighborhood → LLM" bottleneck. Retrieve
  top-k across thousands of notes (dense + BM25 + fuzzy, RRF-fused), rerank with a **local
  cross-encoder**, then feed the LLM only **relevance-extracted spans** instead of an entire
  neighborhood. Also improves auto-linking candidate quality.
- **Source:** **Langroid `DocChatAgent`** (MIT — fully copyable) is the cleanest reference;
  Haystack `DocumentJoiner` + `TransformersSimilarityRanker` is the Apache equivalent; R2R's RRF
  is the minimal version.
- **Offline-safe:** **yes** — BM25 + ST embeddings + local cross-encoder all run on CPU.
- **Effort:** **Medium.** Add a BM25 index alongside vectors + an RRF merge + a small reranker
  model; relevance-extraction is one extra LLM call on a *bounded* candidate set.

### #3 — Schema-guided entity/relation extraction → property graph (upgrade typed edges)
- **Why:** turns grandplan's whole-neighborhood reconciliation into **bounded, schema-constrained
  per-chunk extraction** (no neighborhood scan needed) and makes *entities* first-class nodes —
  dramatically better auto-linking than note-to-note edges alone.
- **Source:** **LlamaIndex `SchemaLLMPathExtractor`** (MIT) — Pydantic schema of allowed entity
  types + relations, validated per path; `SimplePropertyGraphStore` keeps it local. R2R's
  **Triplex** (Phi-3-3.8B, runs in Ollama) is a concrete local extraction *model*.
  **Avoid** txtai (similarity-only graph) and mem0/embedchain (pattern-based NER) for the
  *builder* — grandplan's typed edges are already richer than those.
- **Offline-safe:** **yes** — schema extraction is one LLM call per chunk; Triplex is small/local.
- **Effort:** **Medium–High.** Define the grandplan entity/relation schema, an extraction pass,
  and merge into the existing `Edge` model + `graph.json` projection.

### #4 — Incremental graph maintenance + entity dedup/merge + conflict resolution (bi-temporal)
- **Why:** as the vault grows, re-reconciling whole neighborhoods per change is unsustainable, and
  duplicate/contradictory entities corrupt the graph. Integrate each new note **incrementally**,
  **dedup/merge** entities, and resolve conflicts by **invalidating** superseded edges (validity
  windows) rather than deleting — *lossless by construction*, aligning with grandplan's tombstone
  model and event-sourced substrate (ADR-0008).
- **Source:** **graphiti** bi-temporal model + edge invalidation + node/edge dedup (Apache-2.0);
  **mem0** ADD/UPDATE/DELETE/NOOP classification against k-nearest facts (Apache-2.0);
  nano-graphrag's MD5-hash + entity-name **dedup/merge** routine (MIT) is the most copyable code.
- **Offline-safe:** **yes** — dedup is similarity + small LLM classification on a bounded set.
- **Effort:** **Medium–High.** Build on the existing reconciler; add validity windows to `Edge`
  and a dedup/merge step keyed off block embeddings.

### #5 — Graph-traversal retrieval that does NOT stuff context (PPR + optional community/global)
- **Why:** for corpus-wide questions and scalable neighborhood selection, rank-and-walk the typed
  graph from query-relevant seeds and return only top-k — never feeding the whole neighborhood.
  **Personalized PageRank** is the cheapest entry; **community detection + community reports**
  additionally unlock "themes across all my notes" questions that note-level embeddings
  fundamentally cannot answer.
- **Source:** **fast-graphrag** Personalized PageRank (MIT — simplest to port, cheapest at
  inference); **nano-graphrag** Leiden local/global search + community reports (MIT, ~1.1k LOC);
  LightRAG's dual-level retrieval (MIT) as a middle ground without community-detection cost.
  Memary's **frequency+recency top-N** ranking (MIT, ideas-only) is a tiny complementary bound.
- **Offline-safe:** **yes** — PPR is pure graph compute (NetworkX); community reports add LLM
  summarization cost at index time (run sparingly on 16GB).
- **Effort:** **Medium** for PPR (graph algorithm over existing edges); **High** for full
  community detection + report summarization.

### Priority ordering
1. **#1 chunk embeddings** (unblocks the rest, low risk)
2. **#2 hybrid + rerank + relevance-extraction** (biggest immediate bottleneck relief)
3. **#3 schema-guided extraction** (best auto-linking upgrade)
4. **#4 incremental dedup/conflict resolution** (scaling correctness)
5. **#5 PPR / community retrieval** (corpus-wide scaling; PPR first, community later)

> **Adoption guidance for 16GB/no-GPU offline:** prefer **porting code** over adding heavy deps.
> Lightest/most-copyable references: **nano-graphrag** and **fast-graphrag** (graph), **Langroid
> DocChatAgent** (hybrid retrieval), **LlamaIndex `SchemaLLMPathExtractor`** (extraction),
> **graphiti**/**mem0** (incremental dedup/conflict). Treat **cognee** (wants 32B+), **Letta**
> (fragile tool-calling on small models), **Memary** (unmaintained), and **R2R full mode**
> (Hatchet/Unstructured) as **ideas-only** on this hardware. All licenses are MIT/Apache → code is
> copyable; the binding constraint is CPU/RAM and engineering effort, not licensing.

---

## Appendix — verification ledger (GitHub API, 2026-06-19)

| Repo | Stars | SPDX |
|---|---:|---|
| microsoft/graphrag | 33,867 | MIT |
| HKUDS/LightRAG | 36,781 | MIT |
| gusye1234/nano-graphrag | 3,889 | MIT |
| SciPhi-AI/R2R | 7,891 | MIT |
| circlemind-ai/fast-graphrag | 3,804 | MIT |
| mem0ai/mem0 | 58,940–58,941 | Apache-2.0 |
| getzep/graphiti | 27,631 | Apache-2.0 |
| supermemoryai/supermemory | 27,205 | MIT |
| letta-ai/letta | 23,416 | Apache-2.0 |
| topoteretes/cognee | 17,910 | Apache-2.0 |
| kingjulio8238/Memary | 2,624 | MIT |
| run-llama/llama_index | 50,228 | MIT |
| deepset-ai/haystack | 25,614 | Apache-2.0 |
| llmware-ai/llmware | 14,833 | Apache-2.0 |
| neuml/txtai | 12,669 | Apache-2.0 |
| langroid/langroid | 4,040 | MIT |

*17 libraries verified (EmbedChain shares the mem0 repo). Stars are point-in-time and drift; the
order-of-magnitude and license columns are the durable signal.*
