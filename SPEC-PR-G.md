# SPEC — PR-G: relational organization (the keystone)

> Addresses RC2 + RC3 in `FINDINGS.md`. Today the **only** edges created come from embedding
> similarity (`relates`); nothing produces the structural edges the planner consumes, so the
> masterplan is flat, the plan never sequences, and connections are "just similar text". PR-G adds
> the missing pipeline stage: **place a new note into the existing graph**.

## Goal

When a note is organized, propose how it fits the graph — its **parent** (`part_of`) and its
**prerequisites** (`depends_on`) — and record those typed edges. The hierarchy, the dependency DAG,
and the sequenced "Now/Blocked" plan (US-8, SPEC §11.1) then materialize from real structure instead
of from text similarity.

## Contracts

### `core/placement.py`
- **`Placement`** (frozen): `parent_id: str | None`, `depends_on: tuple[str, ...]`. Helper
  `edges(note_id) -> tuple[Edge, ...]` → a `part_of` edge to the parent (if any) + a `depends_on`
  edge per prerequisite.
- **`Placer`** (Protocol/Strategy): `place(proposed, embedding, repo) -> Placement`. Called against
  the repo **before** the new note is committed, so candidates are existing notes only (no self-match).
- **`HeuristicPlacer`** (deterministic, offline default): proposes `part_of` only — among the
  most-similar existing notes that are **more abstract** than the new note (lower horizon rank:
  masterplan<goal<project<action), pick the most similar above `part_of_threshold` (0.35). No
  dependency guessing (the heuristic can't infer order reliably) → `depends_on` empty. Builds the
  hierarchy from type + similarity, deterministically.

### `adapters/llm_placer.py`
- **`LlmPlacer`**: prompts the local model with the new note + a bounded list (top-k most-similar,
  default 8) of candidate `{id, title, type, horizon}` and asks for JSON
  `{"parent": <id|null>, "depends_on": [<ids>]}`. Every returned id is **validated against the
  candidate set** (a hallucinated id is dropped); `parent` may not equal a dependency; on any
  failure it falls back to `HeuristicPlacer`. Bounded candidates keep it CPU-friendly; offline (Ollama
  localhost) and a deterministic fallback keep the gate hermetic.

### Wiring
- **CLI** `organize` and `regenerate`: a `placer` runs per note after `commit`; its edges are added
  to the repo (guarded: target must exist and not be self), then the final `write_projections`
  re-renders every note/graph/plan with the new structural edges. `HeuristicPlacer` under `--no-llm`,
  `LlmPlacer` otherwise. `organize_text`'s default `placer=None` (no placement) keeps the core tests
  hermetic; the CLI arg layer supplies the real placer.
- **GUI** capture flow (`app/review.py` + coordinator): a new capture is placed against the existing
  vault and the structural edges are recorded on approve (same append-only path as reconcile links).
- The diagnostic report (PR-F) now shows a non-zero **structural** edge count — the "no structural
  edges" warning clears once placement runs.

## Invariants
- **Append-only / lossless (QAS-2):** placement only ever *adds typed edges*; no stored note or
  original is mutated; a note's content-addressed id is unchanged.
- **Offline (QAS-1):** heuristic is pure; the LLM placer talks only to localhost Ollama. `test_offline`
  stays green.
- **No broken edges:** an edge is recorded only when its target is a real note in the repo.
- Keep the gate green; one PR; single independent review; optional deps lazily imported.

## Deferred (later)
Critical-path scheduling / parallel-batch detection; `blocks`/`next`/`waiting_on` inference (PR-G
records `part_of` + `depends_on`; the others stay manual for now); human review/edit of a proposed
placement in the GUI dialog (PR-G auto-applies the safe additive edges and surfaces them in the report).
