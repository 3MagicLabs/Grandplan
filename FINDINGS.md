# FINDINGS — why the generated graph/plan still feels meaningless

> **Date:** 2026-06-17 · **Status:** diagnosis accepted; remediation = PR-F (trustworthy output)
> then PR-G (relational organization). See HANDOFF.md for the folded roadmap.
>
> Method: read `SPEC.md` §11, the full core pipeline, and — decisively — the **actual generated
> artifacts** in `my-vault/` (`Plan.md`, `graph.json`, the note `.md` files). The live output, not
> the code in the abstract, is what proves each root cause.

## Headline

The **vision and spec are sound** — `SPEC.md` §11 ("one append-only graph; every output is a
projection") is coherent and well-designed. The failures are **implementation/roadmap gaps**, and
the worst is a *missing keystone* the roadmap (PR-A…PR-E) never scheduled. Each symptom the user
reported maps to one of five root causes below.

## Evidence (from the live vault)

- Titles like `cloud ai are not sustainable, need to figure out a way to make some local optimi`
  — raw capture text **truncated mid-word at 80 chars**: the `HeuristicOrganizer._title` signature
  (`core/organize.py:79`), **not** an LLM title.
- Tags like `["finders","also","bounty","bug","event"]` — noise-word keyword counts
  (`core/organize.py:95`), not topical tags.
- Note bodies = the verbatim original, unorganized (no summary, no `- [ ]` action items).
- Note frontmatter lacks the `type/…`, `status/…`, `horizon/…` tags and `aliases` — i.e. these
  files were written by an **older build**, before the structural-tag writer (`core/vault.py:136`).
- All edges in `graph.json` are `"kind": "relates"`. **Zero** `part_of` / `depends_on` / `blocks` / `next`.

## Root causes → symptoms

### RC1 — The LLM is opt-in and degrades *silently*; the vault is 100% heuristic output
- Default CLI organizer is `HeuristicOrganizer` unless `--llm` is passed (`cli.py:61`, `cli.py:114`).
- Even with `--llm`, if Ollama is unreachable/model not pulled, it silently falls back to the
  heuristic (`adapters/ollama_organizer.py:169-173`, logged only at WARNING).
- **Symptoms explained:** "nodes that are just ids/noise", "no meaning", "the local AI sometimes
  makes mistakes and doesn't respond." You were looking at keyword-heuristic output and never knew
  the model didn't run. The fallback is *too* graceful — it hides total LLM absence behind
  plausible-looking garbage.

### RC2 — Nothing ever creates structural/planning edges (THE KEYSTONE GAP)
- Every edge-construction site was audited: the **only** edges produced come from the reconciler's
  embedding similarity (`pipeline.py:97` ← `reconcile.py`). There is **no producer anywhere** for
  `part_of`, `depends_on`, `blocks`, or `next`.
- Yet the planner *consumes* exactly those edges to build hierarchy and the dependency DAG
  (`planner.py:277-331`).
- **Symptoms explained:**
  - "By goal/project" / Masterplan is a **flat list** — every note is a root (no `part_of`).
  - "Now/Blocked" never has anything blocked, no ordering — **no temporal/dependency sequencing**
    (no `depends_on`/`blocks`).
  - The graph's only links are "these two text blobs are similar" → **"connections don't make sense."**
- US-8 and §11.1 were specified, but **no PR (A–E) ever built the edge generator that feeds them.**

### RC3 — Structure derives solely from per-note *type*, assigned in isolation
- `default_horizon` only lifts `goal→Goal`, `project→Project` (`models.py:157-165`). With the LLM
  off, every note collapses to `idea`/`action` → no stratification is possible.
- Even with the LLM on, each capture is classified **alone** — nothing asks "is this new idea
  *part_of* an existing goal?" So structure can't emerge regardless of model quality.

### RC4 — Color is broken in this vault (version skew + stale artifacts)
- Graph color works via `tag:#type/<type>` color groups (`core/project.py:36-71`), which require the
  structural tags the *newer* writer emits (`core/vault.py:136-141`).
- The live notes predate those tags → the color queries match nothing → **uniform grey graph**.
- There is **no "re-organize / re-render an existing vault" path**, so old builds' output lingers and
  the app keeps being judged by stale artifacts.

### RC5 — "bare id" nodes = fragile id-based linking
- Links render as `[[<id>|title>]]` relying on `aliases:[id]` (`core/vault.py:174`). When Obsidian
  hasn't indexed the alias (or an old `[[id]]` link survives), it draws a **phantom node named by the
  id**. The phantom sweep only removes *empty, exactly-16-hex* stubs (`core/project.py:76-93`).
- **Lower confidence / lower priority** than RC1–RC4, but linking by slug/title would be far more
  robust than id+alias.

## Roadmap conclusion

The pipeline today is *capture → organize-one-note → similarity-link*. The spec's promise (a
**structured, stratified, sequenced plan**) needs a stage that does not exist:
**"place this note into the existing graph"** — assign its parent (`part_of`), its prerequisites
(`depends_on`/`blocks`), and lift goals/projects to their horizon. That is the keystone, and it
should land **before** voice capture (the old PR-F).

## Remediation (phased, each shippable + gated)

- **PR-F — Trustworthy organization (RC1 + RC4).** Make the LLM the default; **fail loudly** when
  Ollama/model is unavailable (no silent garbage — surface it in CLI/GUI and keep the raw capture in
  inbox for "organize later"). Add a `grandplan regenerate` command that re-organizes + re-renders
  the whole vault so structural tags + color + clean titles/tags/bodies appear. Add an
  organize-quality QAS so "good output" is measured, not assumed.
- **PR-G — Relational organization, the keystone (RC2 + RC3).** A new placement stage (port +
  heuristic + LLM adapter) that proposes `part_of` / `depends_on` / `blocks` edges for a new note
  against the existing graph (human-approved, append-only — never mutating a stored note), and lifts
  horizons accordingly. This makes the hierarchy, the dependency DAG, and the sequenced Now/Blocked
  plan actually materialize. (RC5's slug-based linking can ride along here.)
- **PR-H — voice capture (offline STT).** The former PR-F, renumbered.

## Invariants to honor (unchanged)
- Lossless/append-only: never mutate a stored note/original; new relationships are **events/edges**,
  current state is **derived** (ADR-0007/0008).
- Keep the gate green; branch off `main`; one PR per slice; single independent review before merge;
  optional deps lazily imported; tests hermetic.
