# SPEC — Act on the vault (organized → accomplished)

> **Status:** in progress. Three independent slices that close the gap between *"my ideas are
> captured, organized, and linked"* and *"I am actually doing them."* Each slice composes primitives
> that already exist — `core/schedule`, `core/planner`, `core/query.VaultQuery`, `core/directive` —
> so this is mostly wiring, not new infrastructure. Extends SPEC-AGENT-KB (slice A3 *is* that spec's
> "Fulfil directives" mode).

## 1. The problem

The vault is full and well-organized. Every remaining gap is about **acting**:

| Ask | Gap today |
|---|---|
| "What's the hardest thing / what gives the most progress?" | `core/schedule` computes exactly this, but **chat can't see it** — chat retrieves by embedding similarity only, so a priority question returns semantically-similar notes, not the bottleneck. Only `grandplan report` surfaces the analytics. |
| "Show me this note's place in the graph and everything connected to it." | `VaultQuery.get_note` returns the full neighborhood, but it's **MCP-only** — no CLI/chat surface, and no way to jump from a search hit to the graph. |
| "Profile this person and connect them to my goals." | The `profile-and-connect` playbook exists and directives persist, but **nothing dispatches them** — `pending()` grows forever until an external MCP agent pulls it. |

## 2. Slices

- **A1 — Focus.** Plan analytics reach the chat surface: a deterministic `/focus` command, plus a
  bounded plan block in the chat prompt so natural-language priority questions are grounded in the
  real DAG instead of vibes.
- **A2 — Navigate.** `grandplan graph <query>`: search → pick → the note's neighborhood grouped by
  edge kind, and `--open` to land on it in Obsidian.
- **A3 — Fulfil.** An **opt-in** runner that drains pending directives through a bounded local
  tool-calling loop, so `profile-and-connect` actually builds the people graph.

Order: A1 → A2 → A3 (ascending size and risk). A1 and A2 are read-only; A3 writes.

## 3. Constraints (inherited, non-negotiable)

Everything in SPEC-AGENT-KB §5 applies. Restated where these slices could violate them:

- **Offline (QAS-1)** — no slice adds egress. A2's Obsidian URI hands a `obsidian://` string to the
  local OS handler; that is not a network call.
- **Lossless / append-only (QAS-2, ADR-0008)** — A1 and A2 are strictly read-only. A3 writes only
  through `VaultWrite`'s append-only tools.
- **Single writer (ADR-0006)** — A3 must not write concurrently with the `CaptureCoordinator`.
- **Curation is user-directed only** — see §5. This is the constraint A3 comes closest to, and the
  one to get right.
- **Degradation** — A1's `/focus` must work with **no model at all** (it is pure projection). A model
  outage may not take the priority view down with it.

## 4. A1 — Focus

### Contract

- `/focus` in `grandplan chat` and the GUI chat panel. **No LLM call.** Renders, from
  `build_plan(repo)`:
  - **critical path** (`critical_path`) — the bottleneck chain, in execution order.
  - **now** (`Plan.now`) — actionable and unblocked.
  - **parallel batches** (`parallel_batches`) — what can run concurrently.
  - **progress** (`roll_up_progress`) — goal/project completion.
- `ChatSession` gains an optional plan-context provider. When set, every turn's prompt carries a
  **bounded** `PLAN CONTEXT` block (caps in §4.2), and the instruction states it is authoritative for
  priority/sequence/progress questions while the retrieved notes remain authoritative for content.

### Bounds (num_ctx is finite — 8192 default)

Retrieval already spends ~4.2 KB (6 notes × 700 chars) plus history. The plan block is capped so it
cannot crowd that out:

| Section | Cap |
|---|---|
| critical path | 8 notes |
| now | 8 notes |
| parallel batches | first 3 batches, 5 notes each |
| progress | 5 goals/projects |

Each line is `title` + short id only — never bodies. Truncation is explicit (`… +N more`), never
silent, so the model is never told a partial list is complete.

### Edge cases

- Empty vault / nothing open → every section empty → block **omitted entirely** (an empty block is
  noise that invites the model to invent).
- All notes in a dependency cycle → `critical_path` returns `()`; the planner reports cycles as
  conflicts. `/focus` says so rather than showing a silently empty path.
- Plan is recomputed **per turn** (the vault mutates under auto-approve capture). `build_plan` is a
  toposort — milliseconds at personal scale; no cache, no staleness.

## 5. A3 — Fulfil (the constraint-sensitive one)

**This slice must not become an autonomous vault sweep.** The standing rules are *no autonomous vault
sweeps* (curation is user-directed only) and *no background enrichment* (capture works inline, then
stops; post-save LLM passes are opt-in). The runner is compatible with both, by construction:

1. **It only ever reads the pending directive queue.** It never enumerates, scans, or samples vault
   notes looking for work. Its entire input is `store.pending()`.
2. **Every directive is an explicit user act.** A directive is content *the user sent* with an
   instruction *the user chose*. Fulfilling it is executing a request already made — the opposite of
   unprompted curation.
3. **Off by default.** It runs only when explicitly invoked. Nothing in `gui` or `up` starts it
   implicitly.
4. **One-shot by default**, `--watch` is opt-in. The default drains what is pending and exits.
5. **Writes respect the review posture.** Proposals go through the existing review gate unless the
   user has opted into auto-approve — the same switch that governs capture.

If a future change would let the runner pick its own work, that breaks (1) and (2) and needs a new
decision from the user, not an inference from this spec.

### Why the queue exists at all

`POST /directive` (the phone, via `serve_intake`), `grandplan directive add`, and folder-watch all
append to `directives.jsonl`. Nothing drains it — `pending()` grows forever until an external MCP
agent pulls it. That is the whole gap.

### Contract

`grandplan directive run -o <vault> [--watch] [--max N] [--interval S] [--no-llm] [--embeddings]`

For each pending directive the runner executes the **structural pipeline** — the same one
`grandplan organize` runs, over the directive's content:

    capture verbatim original → organize → assess (dedup) → place → commit → record placement
      → materialize entities

then `mark_done`. No free-form tool-calling loop: the local model does what small models are good at
(extraction, summarization) and **Python does the control flow**. A 7 B model's multi-step tool
discipline is unproven, and it isn't needed — the playbooks decompose into exactly the steps the
pipeline already performs.

### Only playbooks the pipeline honestly fulfils are auto-run

Marking a directive done that was not actually fulfilled is worse than leaving it pending. So the
runner has an **allowlist**, and everything else stays pending for an MCP agent:

| Playbook | Auto-run? | Why |
|---|---|---|
| `capture-and-file` | **yes** | "Summarize into a note, tag it, place it under the right goal" *is* organize + placer, exactly. |
| `profile-and-connect` | **yes** | Note + entity extraction + placement is its structural core (and the people graph the user is after). Its final "propose a next-step task" step is generative and is **reported as not done**, not silently skipped. |
| `extract-actions` | no | "Create a task note per action item" needs generation the pipeline has no step for. |
| ad-hoc `--prompt` | no | Arbitrary instruction; only an agent can interpret it. |

Skipped directives stay pending and the runner says why, pointing at `grandplan mcp --directives`.

### Review posture

`directive run` commits without a per-note dialog — consistent with `grandplan organize`, which has
never had one. The gate is that the command is **explicitly invoked in the foreground**: the user
chose to run it, over a queue they explicitly fed. The GUI keeps its review dialog; this is the CLI.

### Edge cases

- A directive whose pipeline raises is **left pending** and logged — retryable, never silently
  dropped, and one bad directive must not stop the rest of the run.
- A duplicate of an existing note is skipped (dedup) but the directive **is** marked done: it was
  fulfilled, the answer was just "you already have this".
- The original is stamped with the **directive's own `created`**, not a fresh clock (no hidden
  clock — the same rule the capture path follows).
- `--watch` polls; `--max` bounds a single pass. Both default to off/one-shot.

### Open question

- **Write coordination** — resolve SPEC-AGENT-KB §7 (directive queue vs shared lock) before running
  this concurrently with a live `CaptureCoordinator`. Today it is a separate foreground process over
  the same index; running it while the GUI is capturing is not yet sanctioned.
