# SPEC-SCOPE — chat scoped to your Obsidian graph filter

## 1. Why

Chat retrieval ranks the **whole vault** by cosine similarity and feeds the model the top ~6 notes
(`kb_chat.ChatSession.respond`). That is fuzzy in two directions: an off-topic note that shares
wording can outrank a real one, and a genuinely relevant note sitting at rank #8 never reaches the
model because only the top `top_k` above a `_MIN_SCORE` floor survive.

The user already has a fast, deterministic way to say "these are the notes I care about right now":
the **Obsidian graph Filters box**. Type `career education` (or `#career`, `path:Career/`) and the
graph shows exactly that subset. This spec makes chat **read that same filter back** and restrict
retrieval to the notes it selects — precision from the human filter, relevance ordering from the
embeddings *within* that set. The user picks the universe; chat cannot leave it.

The mechanism is already half-present: `core.project.write_obsidian_config` **writes** the graph's
`search` field into `<vault>/.obsidian/graph.json`. This spec **reads** the same field.

## 2. Contract

`grandplan chat` / the GUI chat window gain a **scope sync**: on request they read the current graph
filter, select the notes it matches, and restrict every retrieval turn to that set until re-synced
or cleared.

Guaranteed when a scope is active: no note outside the matched set is retrieved, cited, or used as
grounding — for chat answers *and* for `/plan` drafting. An empty or narrowing-free filter means
**no scope** (chat behaves exactly as today, over the whole vault) — a strict superset of current
behavior, so nothing regresses when the feature is unused.

**Pinned vs. live-follow.** By default a synced scope is *pinned* — it holds until an explicit
re-sync or clear, so the sandbox only ever changes by a deliberate, visible act. **Live-follow**
(the "follow graph live" checkbox / `/scope live`) instead re-reads the graph filter at the **start
of every turn**, so the scope tracks the filter as the user changes it in Obsidian. It is opt-in
because a scope that shifts between turns without an in-chat action can silently govern the
conversation; pinned is the safe default. A manual sync pins (turns following off); a live refresh
that faults keeps the last resolved scope rather than ending the turn.

## 3. Constraints

1. **Re-apply the filter, don't photograph the screen.** Obsidian persists only the filter *query*
   to disk, never the visible node set. Scope is reproduced by evaluating that query over the notes.
   For the operators we support this is the identical set the user sees.
2. **Loud on divergence, never silent.** The supported operator subset (below) is honored exactly.
   Any unsupported operator is **reported** in the sync summary ("ignored `line:`; scope may be
   broader than your graph"), never quietly dropped. We fail *open* (superset + warning), not closed,
   so a stray token can't silently empty the conversation.
3. **Scope controls retrieval, not the model.** A generative LLM keeps its pretrained knowledge; the
   filter bounds only which *notes* enter the prompt. Fabricating specifics *into* the vault is
   prevented at the write boundary (review gate, verbatim originals), not here.
4. **No new floor.** In scoped mode the human filter is the relevance gate, so scoped ranking drops
   the `_MIN_SCORE` floor (threshold `0.0`, negatives excluded) — every note the user vouched for is
   a candidate, capped only by `top_k`.
5. **Fast path untouched.** Empty `scope_ids` keeps today's `repo.most_similar` call (vec index and
   all). Scoping is additive; the unscoped path does not change.
6. **Dimension-safe.** Scoped scoring skips any note whose stored embedding dimension differs from
   the query's, rather than zipping mismatched vectors and comparing noise.

## 4. Supported filter grammar (subset of Obsidian graph search)

| Token | Meaning | Matched against |
|-------|---------|-----------------|
| `word`, `"a phrase"` | keyword (AND by default) | title + body + tags (substring, case-insensitive) |
| `#tag`, `tag:#tag`, `tag:tag` | tag | `note.tags` (exact or nested `tag/…`) |
| `tag:#type/project`, `tag:#status/done` | kind / status | `note.type` / `note.status` |
| `path:X`, `file:X` | filename | the note's rendered stem (`plan_filenames`) |
| `-term` | negation | note must NOT match `term` |
| `A OR B` | alternation | note matches if any OR-group matches |

**Unsupported → reported, then ignored:** `line:`, `section:`, `block:`, `[property]`, `/regex/`,
parenthesized groups. A filter with **no positive term** (empty, or only `-negations`, e.g.
grandplan's own default `-path:"Plan.md" …`) means **no scope** — the whole vault.

## 5. Files

- `core/scope.py` (pure) — `parse_filter(search) -> ScopeQuery`, `select(query, notes, stems) ->
  frozenset[str]`. No IO.
- `adapters/obsidian_graph.py` — `read_graph_filter(vault_dir) -> str | None` (the one read of
  `.obsidian/graph.json`).
- `app/scope_sync.py` — `ScopeResult` + `resolve_graph_scope(vault_dir, repo)`: read → select →
  human-readable summary + warnings.
- `adapters/kb_chat.py` — `ChatSession.scope_ids` (pinned) + `ChatSession.scope_provider` (live-follow:
  an injected `() -> frozenset[str]` refreshed each turn; the session does no IO itself); scoped
  ranking in `respond`/`draft_plan`;
  `_INSTRUCTION` loosened to grounded-and-smart (facts about the user still come **only** from the
  notes; general knowledge welcome for reasoning/advice; no invented specifics presented as note
  facts).
- `cli.py` — `/scope [sync|off]` in `_chat_repl` (default = sync).
- `app/gui.py`, `app/chat_window.py` — "Chat about my graph filter" button + a scope chip; Qt shell
  is `pragma: no cover`, the logic it calls is `scope_sync` (tested).

## 6. Verification

- `test_scope.py` — grammar: keywords/AND, tags (incl. `type/`, `status/`, nested), `path:`,
  negation, `OR`, quoted phrases; unsupported-operator reporting; no-positive-term → whole vault.
- `test_obsidian_graph.py` — reads `search`; missing/foreign/unreadable config → `None`.
- `test_scope_sync.py` — end-to-end select from a synthetic `graph.json`; summary text; 0-match and
  no-filter messaging; warnings surfaced.
- `test_kb_chat.py` — scoped retrieval excludes out-of-scope notes; empty scope == today; loosened
  instruction still carries the "ONLY notes for user facts" contract and JSON keys.
- `test_cli.py` — `/scope` syncs and prints the summary; `/scope off` clears; disabled with a message
  when no vault is wired.
