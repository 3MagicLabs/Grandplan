# 11. Evaluating organize quality vs latency/memory

- **Status:** Proposed
- **Date:** 2026-06-25

## Context

"Does it organize *well*, and what does that cost?" (issue #25) has two measurable dimensions:

1. **Quality** — how good is dedup + linking? Driven by the embedder and the reconcile thresholds
   (`link_threshold`, `duplicate_threshold`).
2. **Cost** — per-capture latency and index memory. Driven by vault size and the model/embedder.

Two reproducible, offline harnesses now exist:

- `scripts/eval_retrieval.py` — a small **labeled** paraphrase set (clusters that should link, plus
  unrelated notes that should not); reports duplicate/link precision/recall/F1 + a threshold sweep.
- `scripts/bench_reconcile.py` — latency + index memory at 100/1k/10k notes (see ADR-0009).

## Findings (offline baseline — `HashingEmbedder`, 21 notes / 210 pairs / 27 same-concept)

| Decision | threshold | precision | recall | F1 |
|----------|----------:|----------:|-------:|---:|
| link     | 0.30      | 0.61      | 0.41   | 0.49 |
| duplicate| 0.90      | 1.00*     | ~0     | —  |

\* No paraphrase pair reaches 0.90 with bag-of-words, so duplicate-detection fires **only on near-exact
text** — i.e. it never false-merges distinct ideas (precision 1.0 by construction; recall low *on
paraphrases* — which is intended, see Decision).

Link-threshold sweep (precision ↔ recall trade-off):

| threshold | 0.10 | 0.20 | **0.30** | 0.40 | 0.50 |
|-----------|-----:|-----:|---------:|-----:|-----:|
| precision | 0.26 | 0.43 | **0.61** | 0.86 | 1.00 |
| recall    | 0.85 | 0.56 | **0.41** | 0.22 | 0.04 |

Cost (from ADR-0009): per-capture reconcile p95 ≈ 8 ms @100 notes, 57 ms @1k, 319 ms @10k; index memory
~8.4 MiB / 1k notes.

## Decision

1. **Keep the shipped thresholds** — `link = 0.30` (the balanced F1 knee) and `duplicate = 0.90`
   (near-exact only). For a **lossless, review-first** tool a false *merge* is far worse than a missed
   *link* (the user can always link manually; an auto-merge loses structure), so a conservative
   duplicate threshold and a precision-leaning link threshold are the right defaults. The two-tier
   design (cheap dot-product for all, LLM classifier only on the top-k) already bounds the LLM cost.
2. **Recommend the sentence-transformer embedder** (`[embeddings]` extra) when recall matters: the
   bag-of-words baseline favours precision (shared words drive similarity) and misses heavy
   paraphrases; a dense embedder is expected to raise recall without moving the thresholds.
3. **LLM-organize quality is evaluated on the user's machine** (needs Ollama). The harness: run a fixed
   set of messy captures through `gemma3:4b` (capture default) vs `qwen2.5:14b` (earmarked KB model),
   score title/type/tags against a rubric, and record p50/p95 latency + RAM per model — turning the
   model choice into data rather than vibes. Captured as a follow-up so the offline gate stays
   model-free.

## Quality-attribute scenarios (QAS)

- **QAS-QUAL-1 (linking):** link F1 ≥ 0.45 on the labeled set. — **met** (0.49, baseline embedder).
- **QAS-QUAL-2 (no false-merge):** duplicate-detection precision = 1.0 (never merges distinct ideas).
  — **met** (near-exact only).
- **QAS-QUAL-3 (cost):** per-capture reconcile p95 ≤ 150 ms at personal scale. — **met** to ~3–5k notes
  (ADR-0009); the swap trigger is shared with the scalability ADR.

## Consequences

- The default thresholds are now **justified by measured precision/recall**, not guesses, and the
  trade-off is re-runnable as the embedder or data changes.
- A clear quality-upgrade path (dense embedder) and an LLM-model eval rubric are recorded.
- The offline quality eval runs in CI-friendly time with zero model dependency; the LLM dimension is
  explicitly deferred to a machine with Ollama, keeping the gate offline.
