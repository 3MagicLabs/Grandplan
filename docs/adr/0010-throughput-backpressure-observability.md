# 10. Throughput & backpressure under serialized capture

- **Status:** Proposed
- **Date:** 2026-06-25

## Context

`CaptureCoordinator` serializes every capture through one worker thread (ADR-0006): organize (local
LLM) → embed → reconcile → review → commit, one at a time. This is deliberate — it guarantees a single
writer to the non-thread-safe repo/vault and ensures only one local-model call runs at a time (so the
runtime can't fan out into parallel copies and exhaust RAM on the 16 GB target).

The cost (issue #3): under rapid captures — especially with `--embeddings`, where each capture is
heavier — a backlog forms behind the one in flight, and the UI previously sat "busy" with **no signal
of how deep the queue was or whether work was lost**. The question: should we pipeline to raise
throughput, and how do we make backpressure visible?

## Decision

**Keep the single-writer serialization (ADR-0006); do not pipeline now.** Instead, make backpressure
**observable** and rely on the existing bounded queue for safety:

1. **Surface queue depth.** `CaptureCoordinator` exposes `pending_count()` and `capacity()`, and every
   emitted `CaptureStatus` now carries `pending` (captures still waiting behind the one in flight),
   which `progress_for` maps to `ProgressView.queued`. The popup can render "+N waiting", so a backlog
   is visible rather than an opaque spinner.
2. **Bounded buffer = explicit backpressure.** The queue is capped at `max_pending` (default 16). When
   full, `submit()` is **rejected with a visible `REJECTED_BUSY` status** — never silently dropped or
   stacked. That is the backpressure contract.
3. **Reject pipelining for now, with the seam identified.** Evaluated overlapping stages of adjacent
   captures. The LLM organize is the bottleneck, but it cannot overlap the next capture's reconcile/
   commit without violating the single-writer repo invariant, and running two model calls at once would
   thrash RAM on the target box. Human review is also inherently serial. So pipelining buys little for
   real risk. **If** measured throughput ever demands it, the safe seam is overlapping the *embed of
   the next* capture with the *human review of the current* one (both off the repo-write path) — left
   as a future ADR, gated on a measured need.

## Quality-attribute scenarios (QAS)

- **QAS-THRU-1 (no silent loss):** under a burst exceeding `max_pending`, every excess capture produces
  a visible `REJECTED_BUSY` and nothing is stacked or dropped. — **met** (bounded queue + status).
- **QAS-THRU-2 (visible wait):** while captures are queued, the user can always see the queue depth.
  — **met** (queue depth surfaced through `CaptureStatus.pending` → `ProgressView.queued`).
- **QAS-THRU-3 (ETA):** show an estimated wait, not just a count. — **deferred**: a true ETA needs a
  rolling average of per-capture duration × queue depth; cheap to add once stage timings are recorded,
  but out of scope here (the count is the useful 80%).

## Consequences

- The serialization guarantee (ADR-0006) is preserved — no new concurrency on the repo/model path.
- Backlogs are now legible (depth surfaced) and overflow is explicit (`REJECTED_BUSY`), which was the
  actual felt problem; throughput itself is unchanged by design.
- A concrete, invariant-safe pipelining seam (embed-next ∥ review-current) and an ETA approach are
  recorded for later, so the decision can be revisited with data rather than re-derived.
- Pure additions (`pending_count`, `capacity`, `CaptureStatus.pending`, `ProgressView.queued`) are
  unit-tested in the Qt-free layer; the GUI widget stays a thin renderer.
