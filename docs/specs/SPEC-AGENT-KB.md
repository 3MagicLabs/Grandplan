# SPEC — Future knowledge-base agent (design spike)

> **Status:** design spike (not built). Sketches the future **KB agent** that reasons over the
> *completed* vault, distinct from the latency-sensitive capture loop. Grounded in primitives that
> already exist — `core/query.VaultQuery`, the MCP read/write/directive tools, and the directive
> spine — so this is mostly *composition*, not new infrastructure. Issue #26.

## 1. What it is (and isn't)

The **capture loop** (hotkey → organize → review → file) is frequent, interactive, and runs a small
fast model (`gemma3:4b`, ADR-aligned with the two-model strategy). The **KB agent** is its opposite:
**infrequent, reasoning-heavy, background**, working over the *whole* knowledge base once it exists. It
gets its **own model setting** — default **`qwen2.5:14b`** — never reusing the capture `DEFAULT_MODEL`.

It is **not** a new store or pipeline. It is an **agent (LLM loop) that drives the existing
agent-operable vault** (SPEC-AGENT-VAULT): the read facade, the append-only write tools, and the
directive spine. Think "Claude Desktop pointed at `grandplan mcp`, but local, scheduled, and
KB-specialized."

## 2. Three modes

1. **Ask (read-only Q&A).** "What's blocking the launch?", "Summarize everything I captured about
   X", "What contradicts note Y?". Uses only the read API. Zero write risk. The first thing to ship.
2. **Garden (propose, review-gated).** Periodically scan the KB for entropy the capture loop can't see
   with only-local context: stale `now`/blocked items, orphan notes, near-duplicates that slipped the
   0.90 threshold, contradictions, missing links between related clusters. Emits **proposals**, never
   silent edits.
3. **Fulfil directives.** Pull higher-level `Directive`s (the same spine the HTTP intake / folder-watch
   feed) whose `instruction` needs reasoning over the KB ("draft a plan from my Q3 notes"), execute via
   the read/write tools, `mark_done`.

## 3. Architecture (reuse, don't rebuild)

```
                 ┌─────────────── KB agent (qwen2.5:14b, background) ───────────────┐
   directives ──▶│  loop: retrieve → reason → propose → (review) → append-only write │
   (intake)      └───────┬───────────────────────┬───────────────────────┬──────────┘
                         │ read                    │ write (append-only)   │ directives
                         ▼                         ▼                       ▼
                  core/query.VaultQuery     MCP WRITE_TOOLS         directive spine
            (search_notes, get_plan,    (set-status / edit / link / (pending → mark_done)
             get_masterplan, get_graph,  resource / propose-note,
             get_note, doctor)           all event-sourced ADR-0008)
                         │
                         ▼
                 vault + index (notes, edges, embeddings, event log)
```

- **Read** via the existing `VaultQuery` facade (already JSON-serializable, offline, tested). No new
  read code needed.
- **Write** only through the append-only event tools (ADR-0008): the agent **never mutates** a note or
  an original; it appends `status` / `edit` / `link` / `resource` events, or proposes a new note. All
  orphan-guarded and idempotent (existing invariants).
- **Coordinate** with the capture writer: the KB agent must not write concurrently with the
  `CaptureCoordinator`'s single writer (ADR-0006). Two safe options — (a) the agent enqueues its writes
  as **directives** the same serialized worker drains, or (b) a single shared write lock. Prefer (a):
  it reuses the spine and keeps one writer.

## 4. Retrieval

- **Now:** `search_notes` (embedding similarity) + `get_graph` / `get_masterplan` for structure. Good
  enough for Ask mode at personal scale (ADR-0009 latency budget).
- **Next:** a **local knowledge-graph retrieval** layer (LightRAG-style, per the 2026 research refresh)
  — the vault already has `entity` nodes + `involves`/typed edges, so dual-layer (vector + graph)
  retrieval is incremental, runs on Ollama, and improves multi-hop reasoning. Reserve for the 7–14 B
  tier (the KB model), which meets LightRAG's "needs a capable LLM" caveat.

## 5. Constraints (inherited, non-negotiable)

- **Offline** — qwen2.5:14b via local Ollama; zero egress.
- **Lossless / append-only** — originals and notes never mutated; only events appended.
- **Review-first for anything destructive-ish** — merges, supersessions, status flips that leave "now"
  are **proposed**, surfaced to the human (reuse the review controller), applied on approval. Consistent
  with ADR-0011 (never false-merge) and the existing capture review flow.
- **Modest hardware** — 14 B at Q4_K_M fits 16 GB *because* the KB agent runs **infrequently** (manual
  "ask", or a scheduled nightly garden), so it can afford the heavier model the capture loop cannot.

## 6. Phasing

- **P1 — Ask.** Read-only Q&A agent over `VaultQuery`, own `--kb-model` (default qwen2.5:14b), CLI
  entry (`grandplan ask "…"` or an MCP client). No writes. Smallest, safest, immediately useful.
- **P2 — Garden.** Scheduled scan emitting review-gated proposals (links, status, dedup, contradiction
  flags) through the directive/review path. Measure precision of proposals (extend `eval_retrieval.py`).
- **P3 — KG retrieval.** Add the dual-layer (vector + entity-graph) retrieval; benchmark answer quality
  vs vector-only.

## 7. Open questions

- **Review ergonomics for background proposals** — a batched "morning review" queue vs inline prompts.
- **Scheduling** — on-demand only, or a local scheduler for the nightly garden (must stay offline).
- **Model availability** — graceful degradation when qwen2.5:14b isn't pulled (fall back to the capture
  model for Ask, refuse Garden) — verify current Ollama tags at build time (models go stale fast).
- **Write coordination** — confirm the directive-queue path (4a) end-to-end vs a shared lock.
