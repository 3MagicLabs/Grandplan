# 7. Richer reconciliation: relationship classification + consistency-by-projection

- **Status:** Accepted
- **Date:** 2026-06-17

## Context

US-10 / #12: a new note related to an existing thread must be **reconciled** with it — not just
"related/duplicate" (the `SimilarityReconciler` baseline), but `builds_on` / `refines` /
`supersedes` / `contradicts` — "so my knowledge stays consistent, not duplicated or stale" (SPEC
§11.2). The schema is already forward-ready (`EdgeKind` and `NoteStatus` carry the needed values,
SPEC §11.5); what's missing is the **classification** and the **consistency maintenance**.

Two tensions:
1. Cosine similarity alone cannot tell `builds_on` from `supersedes` from `contradicts` — those are
   *semantic* judgments. SPEC says they are **LLM-proposed, human-approved**. But the gated core must
   stay offline and deterministic.
2. SPEC says `supersedes` → "old kept (append-only)" and `contradicts` → "set status: needs-review".
   Yet the **lossless/append-only invariant is the top priority (QAS-2)** and `Note` is immutable;
   the repository never mutates a stored note.

## Decision

**Classification = Strategy behind the `Reconciler` port** (mirrors `Organizer`):
- A `RelationshipClassifier` port classifies `(new proposal, candidate note, similarity) → Relationship`.
- The deterministic **`SimilarityClassifier`** baseline reproduces today's behaviour (DUPLICATE vs
  RELATED bands) and is the **default**, so existing behaviour and tests are unchanged.
- An **`LlmRelationshipClassifier`** adapter (injected `chat`, deterministic fallback to the baseline)
  proposes the richer kinds — its parsing/validation/fallback are unit-tested with a fake `chat`;
  the real model call is integration-tested on Windows. `SimilarityReconciler` composes: rank by
  cosine, then classify each candidate via the injected classifier.

**Consistency = projection, never mutation** (preserves append-only/lossless):
- Each non-duplicate relationship maps to a typed `Edge` the human approves (`builds_on`, `refines`,
  `supersedes`, `contradicts`, or `relates`). The edge is authoritative.
- **`supersedes`:** the new note is committed normally + a `supersedes` edge (new → old). The old
  note is **not mutated**; the `Planner` *derives* "superseded" from an **incoming `supersedes`
  edge** and excludes it from the actionable plan — same effect, zero mutation.
- **`contradicts`:** never auto-resolved — both notes kept, a `contradicts` edge added, and the **new
  note is created** with `status = needs-review` (set at creation, not a mutation of an existing
  note). The `Planner` surfaces a **"Needs review"** section (needs-review notes + contradictions).

`commit` is generalized to take typed `links` (note + edge kind) and an explicit `status` (defaulting
to today's values), so the CLI and the GUI's review/approve path wire through unchanged.

## Consequences

- The full classification → consistency → projection path is **deterministic and gated in WSL2**
  (the baseline + the consistency rules + the planner projection); the LLM only *proposes* labels and
  is swappable behind the port (QAS-5).
- Append-only/lossless is preserved: no stored note is ever mutated; "superseded" and "needs-review"
  are derived from edges/creation-time status, consistent with "graph is the source of truth, plans
  are projections" (ADR-0004).
- MVP slice (SPEC §11.6): duplicate + build-on + supersede + contradict-flag. `refines` is supported
  as a link kind; richer LLM-driven merge/consistency loops remain future work.
