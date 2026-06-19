# SPEC — PR-F: trustworthy organization

> Addresses RC1 + RC4 in `FINDINGS.md`. The live vault is keyword-heuristic output (the LLM is
> opt-in and degrades *silently* when Ollama is down) and partly from an old format (no color tags).
> PR-F makes the model the **default**, makes its absence **loud**, and lets the user **regenerate**
> an existing vault to current quality.

## Goal

A user running grandplan gets **real LLM organization by default**, and if the local model can't
run they get a **clear, actionable error** (model preserved capture, here's how to fix) — never
silent keyword garbage presented as organized output.

## Contracts

### 1. Fail-loud organizer (RC1)
- **`adapters/ollama_organizer.py`** adds `class OrganizerUnavailable(RuntimeError)` and a
  `require: bool = False` constructor flag.
  - `require=False` (default, unchanged): on exhausted retries, degrade to the `HeuristicOrganizer`
    fallback — keeps the deliberate offline baseline and every existing test green.
  - `require=True`: there is **no fallback**; `organize()` raises `OrganizerUnavailable(model)` after
    its retries, with guidance ("start Ollama / `ollama pull <model>`, or use the offline baseline").
- **Lossless invariant preserved:** the verbatim `Original` is added to the inbox in `pipeline.propose`
  *before* `organize()` is called, so a raised `OrganizerUnavailable` never loses the capture — the
  CLI reports it; the GUI coordinator already catches it (`Stage.FAILED`) and keeps the inbox copy.

### 2. LLM is the default (RC1)
- **CLI** `organize` and `gui`: the local model is **on by default**. Add `--no-llm` to opt into the
  offline baseline deliberately; keep `--llm` as an accepted (now-redundant) flag so existing
  `run.bat` / muscle memory don't break. `use_llm = not args.no_llm`.
- The CLI constructs `OllamaOrganizer(model=..., require=True)` so a missing model fails loud with a
  tailored message (start Ollama / pull the model / `--no-llm`), exit code 1, nothing written.
- **GUI** `run_app(use_llm=True default)` + `require=True`; the coordinator surfaces `OrganizerUnavailable`
  as `FAILED` with the message and the raw capture stays in the inbox (re-organize later).
- `--embeddings` stays **opt-in** (it needs the heavy extra; default-on would break hermetic CI and
  modest installs). Out of PR-F scope.

### 3. Regenerate an existing vault (RC4)
- **CLI** `grandplan regenerate -o <vault> [--no-llm] [--embeddings] [--model M]`: rebuild the derived
  notes/edges **from the lossless `inbox.jsonl` originals** through the current organize→embed→
  reconcile→link pipeline, then write a fresh `graph.json` / `Plan.md` / `Masterplan.md` and re-render
  every note `.md` in the current format (structural color tags, clean titles/bodies, resolved links).
  - Distinct from `rerender` (which only re-renders the *stored* notes in the current file format,
    without re-organizing). `regenerate` re-runs the **organizer**, so heuristic-era notes become
    real LLM notes.
  - **Append-only honesty:** re-organizing changes a note's content-addressed `id`, so `regenerate`
    builds a *new* index from the originals (the event log of the old, low-value heuristic notes is
    not carried over — this is an explicit, user-invoked rebuild). The **originals are never mutated**
    (QAS-2 intact); the prior `index.jsonl` is backed up to `index.jsonl.bak` before the rebuild so
    nothing is irreversibly lost.
  - Fails loud the same way (`require=True` unless `--no-llm`); if Ollama is down it aborts before
    touching the index.

### 4. Organize-quality QAS (measure, don't assume)
- Add **QAS-8 (organize quality)** to `SPEC.md` §4 and a gated test: for a corpus of representative
  captures, an LLM-organized note must have a title that is **not** a verbatim truncation of the
  body's first line, **≥1** topical (non-stopword) tag, and a body containing a one-line summary.
  Run against a *fake* deterministic organizer in CI (hermetic); the real-model check is a
  documented manual/integration step on the user's machine.

## Invariants
- Lossless/append-only: originals never mutated; `regenerate` backs up the old index, never the inbox.
- Hermetic gate: `organize_text`'s default organizer stays the offline baseline (the LLM default is
  applied only in the CLI/GUI arg layer, which tests drive with explicit injects); no network in tests.
- Keep the gate green; one PR; single independent review; optional deps lazily imported.

## Out of scope (→ PR-G)
Creating structural `part_of` / `depends_on` / `blocks` edges and horizon lift (the relational
keystone) — PR-F only fixes *per-note* quality and the silent-degradation bug.
