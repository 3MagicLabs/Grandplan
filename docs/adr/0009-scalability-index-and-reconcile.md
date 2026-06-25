# 9. Scalability of the in-memory index and reconcile search

- **Status:** Proposed
- **Date:** 2026-06-25

## Context

Every capture runs `reconcile`, which calls `repo.most_similar(embedding)` — a brute-force scan that
dot-products the new embedding against **every** stored note's embedding (`InMemoryNoteRepository`,
256-dim unit vectors). The whole index lives in memory. Two scaling questions for sustained personal
use (issue #4): does per-capture latency stay acceptable, and does the index fit in RAM on the 16 GB
target?

`scripts/bench_reconcile.py` measures this offline (HashingEmbedder + the in-memory repo, single
core, pure Python). Indicative numbers — the *shape* matters more than absolute ms:

| N notes | index memory | `most_similar` p50 | p95 | full-vault rebuild (N searches) |
|--------:|-------------:|-------------------:|----:|--------------------------------:|
| 100     | 0.8 MiB      | 2.3 ms             | 8.4 ms  | 0.2 s |
| 1,000   | 8.4 MiB      | 32 ms              | 57 ms   | 32 s  |
| 10,000  | 84 MiB       | 245 ms             | 319 ms  | ~41 min |

Reading: **per-query cost is O(N)**, so a single capture's reconcile stays interactive into the low
thousands of notes and is still ~0.3 s at 10k. **Memory is linear** (~8.4 MiB / 1k notes; ~840 MiB
projected at 100k — large but survivable on 16 GB). The real cliff is the **O(N²) full-vault rebuild**:
`regenerate` (and any cold reproject) reconciles once per note, so rebuilding a 10k-note vault spends
**tens of minutes** purely in similarity search. A real sentence-transformer embedder raises the
constant (denser vectors) but not the asymptotics.

## Decision

**Keep the in-memory brute-force index as the default.** At realistic personal scale (hundreds to a
few thousand notes) it is well within budget, dependency-free, and offline — consistent with the
project's constraints. We do **not** add an ANN/vector-DB dependency now (premature; it adds a heavy
dependency and an index-staleness failure mode for a scale most users won't hit).

Instead:

1. **Treat the index representation as an adapter secret behind the stable `NoteRepository` port.**
   The port already exposes `most_similar(...)`; no core code knows it is brute force. An ANN / on-disk
   adapter can replace `InMemoryNoteRepository` with **zero core changes** (the SQLite + sqlite-vec
   path already anticipated in `repository.py`).
2. **Define quality-attribute scenarios (QAS) as the trigger to swap:**
   - **QAS-SCALE-1 (latency):** p95 single-capture reconcile ≤ 150 ms. Crossed around **~3–5k notes**
     with the current brute force → the swap trigger.
   - **QAS-SCALE-2 (memory):** resident index ≤ 512 MiB. Crossed around **~60k notes**.
   - **QAS-SCALE-3 (rebuild):** `regenerate` of the whole vault ≤ 60 s. Crossed around **~1.3k notes**
     — the earliest-binding limit, and the strongest argument for an on-disk vector index once a user's
     vault is large *and* they rebuild often.
3. **Cheap wins available before any ANN work** (smaller, port-preserving): skip the per-query
   `_is_deleted` event scan by maintaining a tombstone set (today `most_similar` is O(N·E) when the
   event log E is large); and let `regenerate` reuse a single warm index instead of re-searching from
   cold. These are follow-ups, not part of this ADR.
4. **Ship the benchmark** (`scripts/bench_reconcile.py`) so the thresholds above are re-measurable on
   real hardware / real embedders before committing to an adapter.

## Alternatives considered

- **sqlite-vec behind the port (recommended when QAS trips).** On-disk vector index in the existing
  SQLite store; offline, no service, modest dependency; turns search into an indexed lookup and fixes
  both the O(N²) rebuild and the memory ceiling. Best fit for the project's offline/modest-hardware
  constraints. Deferred until a QAS trips.
- **hnswlib / FAISS (in-process ANN).** Fast approximate search, but a heavier binary dependency and
  an in-memory index to persist/rebuild — more machinery than personal scale warrants.
- **Do nothing / cap vault size.** Rejected: silently degrades for power users; the port makes the
  swap cheap enough that an artificial cap is unnecessary.
- **Add the ANN index now.** Rejected as premature optimization: real cost (dependency, staleness
  bugs) for a scale most users won't reach; the measured headroom is large.

## Consequences

- The brute-force default stays simple, offline, and dependency-free; the port keeps the door open.
- We have **measured** trigger thresholds (latency ~3–5k, rebuild ~1.3k, memory ~60k notes) instead of
  guesses, and a re-runnable benchmark to confirm them on real hardware.
- When QAS-SCALE-1/3 trips, the planned work is a sqlite-vec `NoteRepository` adapter + a follow-up ADR
  recording the chosen index and its recall/latency trade-offs — no core or contract change.
- Two cheap, port-preserving optimizations (tombstone set, warm-index rebuild) are identified for when
  they're worth it, independent of the bigger ANN decision.
