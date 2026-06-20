# Prior-Art Adoption — learning from successful PKM / local-AI tools

**Purpose.** Survey high-traction open-source tools adjacent to grandplan, extract the
features/techniques behind their success, and propose what to adopt — **every proposal filtered
through grandplan's non-negotiables**: offline-only · lossless · local LLM · 16GB no-GPU.

**Status.** Research only. Nothing here is implemented. Decide scope together before any feature code.

**Method.** Candidate repos were verified live via the GitHub API (star counts + last-push date as of
**2026-06-19**); techniques were extracted from each project's README/docs. No repo is cited without a
verified star count, to avoid chasing projects that don't exist or aren't maintained.

---

## 1. The verified landscape

| Project | Stars | Last push | What it is | Closest to grandplan on… |
|---|--:|---|---|---|
| [usememos/memos](https://github.com/usememos/memos) | 60.9k | 2026-06-19 | Lightweight quick-capture note tool | Capture UX |
| [AppFlowy](https://github.com/AppFlowy-IO/AppFlowy) | 72.6k | 2026-06-18 | Notion-style workspace + AI | Planning/action |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | 61.8k | 2026-06-19 | Local RAG over your docs | AI organization |
| [mem0](https://github.com/mem0ai/mem0) | 58.9k | 2026-06-19 | Memory layer for agents | AI organization |
| [private-gpt](https://github.com/zylon-ai/private-gpt) | 57.3k | 2026-06-18 | 100%-private doc Q&A | AI organization (offline) |
| [joplin](https://github.com/laurent22/joplin) | 55.3k | 2026-06-19 | Privacy notes + web clipper | Capture UX |
| [siyuan](https://github.com/siyuan-note/siyuan) | 44.5k | 2026-06-19 | Local-first block PKM | Knowledge graph |
| [logseq](https://github.com/logseq/logseq) | 43.5k | 2026-06-19 | Local-first outliner + queries | Planning/action, graph |
| [QuivrHQ/quivr](https://github.com/QuivrHQ/quivr) | 39.2k | 2025-07-09 | Opinionated RAG | AI organization |
| [TriliumNext/Trilium](https://github.com/TriliumNext/Trilium) | 36.5k | 2026-06-19 | Hierarchical PKM | Knowledge graph |
| [khoj](https://github.com/khoj-ai/khoj) | 35.2k | 2026-03-26 | AI second brain, self-hostable | AI organization, capture |
| [onyx](https://github.com/onyx-dot-app/onyx) | 30.4k | 2026-06-19 | Open AI platform / connectors | AI organization |
| [supermemory](https://github.com/supermemoryai/supermemory) | 27.2k | 2026-06-19 | Memory/context engine | AI organization |
| [karakeep](https://github.com/karakeep-app/karakeep) | 26.1k | 2026-06-14 | Save-everything + AI auto-tag | **Capture UX + AI org** |
| [obsidian-releases](https://github.com/obsidianmd/obsidian-releases) | 18.9k | 2026-06-19 | Obsidian plugin ecosystem | (ecosystem) |
| [foam](https://github.com/foambubble/foam) | 17.2k | 2026-06-18 | VSCode PKM, backlinks/graph | Knowledge graph |
| [notesnook](https://github.com/streetwriters/notesnook) | 14.2k | 2026-06-19 | E2E-encrypted notes | (constraint conflict) |
| [reorproject/reor](https://github.com/reorproject/reor) | 8.6k | 2025-05-13 | **Local AI PKM, auto-linking** | **Closest overall analog** |
| [obsidian-copilot](https://github.com/logancyang/obsidian-copilot) | 7.2k | 2026-06-19 | LLM copilot in Obsidian | AI organization |
| [smart-connections](https://github.com/brianpetro/obsidian-smart-connections) | 5.2k | 2026-06-19 | **Local-embedding related-notes** | **Knowledge graph technique** |

**Headline finding.** grandplan's exact thesis (capture → local LLM → atomic, linked, lossless
vault) is most directly mirrored by **Reor** (auto-linking via local embeddings + Ollama RAG) and
**Karakeep** (frictionless multi-channel capture + LLM auto-tagging). grandplan's *differentiators*
— lossless verbatim preservation, event-sourced substrate, human-approval gate, an actionable plan —
remain genuinely rare. The opportunities below are about **closing UX/feature gaps**, not changing the thesis.

---

## 2. What grandplan already has (so we don't reinvent it)

Confirmed in `src/grandplan/`: global-hotkey **selection capture** (clipboard/UIA),
local-LLM **organize** (atomic, verbatim-preserved), **embeddings + linking + dedup**, **wikilinks**,
JSON **knowledge graph**, **Plan.md** + **dependency model + Timeline**, **context-aware reconcile**
(whole-neighborhood RAG), **summaries/digest**, **tasks**, a read-only **VaultQuery + MCP server**,
**calendar connector**, event-sourced substrate with **tombstones**. ~600 tests, borromeo-gated.

**Confirmed real gaps** (grep-verified absent or thin): no `backlink` index, no `ocr`, no file
`watch`er, no `agenda`/today view, note-level (not **block/chunk**) embedding granularity, and the
graph is **JSON-only** (no interactive view). `query.py` is an agent read-facade, not a user-facing
Dataview-style dynamic query.

---

## 3. Adoption proposals by dimension

Each item: **what the leaders do → grandplan gap → proposal (offline-safe).**

### A. Capture UX
- **Multi-channel, frictionless capture** — *Karakeep* (browser ext, share sheet, mobile, API, PDF/image),
  *Memos* (one-box quick capture), *Joplin* (web clipper). grandplan captures **text selection only**.
  - **A1 — Quick-capture box:** a tiny always-available text input (separate hotkey) for typing/pasting
    a thought without selecting it first. Pure-offline, small. **High value, low effort.**
  - **A2 — Inbox-folder watcher:** drop `.md`/`.txt`/image into a watched folder → auto-ingested through
    the same organize pipeline. Enables phone→synced-folder→grandplan without any network in grandplan.
  - **A3 — Local OCR capture:** capture an image/screenshot region; extract text via **local Tesseract**
    (lazy-imported optional extra) so screenshots/PDFs become losslessly-stored notes. Offline-safe.
- *Rejected:* RSS auto-hoarding, remote-URL web archival (Karakeep/Joplin) — **network egress, violates offline-only.**

### B. AI organization
- **Block/chunk-level embedding** — *Reor* ("every note is chunked and embedded"), *smart-connections*
  (block-granular matches). grandplan embeds at **note level**.
  - **B1 — Chunk-level embeddings:** embed paragraphs/blocks, not whole notes, for sharper related-notes
    and reconcile. Biggest quality lever; touches `embed.py` + index. **High value, medium effort.**
- **LLM auto-summary + rule engine** — *Karakeep* ("LLM tagging + summarization" + **rule-based engine**).
  - **B2 — Deterministic rule layer:** user rules (`if tag/source/keyword → route/tag/link`) that run
    *before/around* the LLM — cheaper, predictable, testable; complements the model. Fits the gate ethos.
- *Rejected:* cloud-model defaults (Khoj/AnythingLLM OpenAI paths) — local LLM is non-negotiable. mem0's
  hosted memory — same. Keep these as *interface inspiration* only.

### C. Knowledge graph
- **Suggest-don't-impose linking** — *smart-connections* ranks related notes by similarity and lets you
  **drag to create a link** (intentional, not auto). This matches grandplan's lossless/approval ethos.
  - **C1 — Related-notes panel at review time:** during the approval step, surface top-k semantically
    related notes (with score) and offer one-click `[[link]]`. Leverages existing embedder. **High value.**
- **Backlinks + interactive graph** — *Foam/SiYuan/Logseq* (backlinks pane, graph view). grandplan has
  `graph.json` only.
  - **C2 — Backlink index:** derive inbound links per note (cheap from existing edges) and render a
    "Linked mentions" section. **Low effort.**
  - **C3 — Offline graph view:** a single self-contained HTML (no CDN) rendering `graph.json` for visual
    navigation. Optional, **medium effort.**

### D. Planning / action
- **Dynamic queries & agenda** — *Logseq* (Datalog queries, TODO states, scheduled/deadline), *AppFlowy*
  (views). grandplan has a static `Plan.md` + Timeline.
  - **D1 — Saved dynamic views:** Dataview-style queries over the SQLite index (e.g. "open tasks by
    project", "captured this week") rendered into regenerated `.md`. Reuses `query.py`. **Medium effort.**
  - **D2 — Daily digest / Today:** combine calendar connector + due tasks + recent captures + suggested
    links into a generated "Today" note. *Khoj*-style automation, but **local + offline**. **High value.**
- *Rejected:* multiplayer/collab boards (AppFlowy), e2e-encrypted sync (Notesnook) — out of scope/constraint.

---

## 4. Prioritized recommendation

Scored for **value**, **effort**, and **constraint-fit** (all listed items are offline-safe).

| Pri | Item | Why now | Value | Effort |
|---|---|---|---|---|
| **P0** | **C1** Related-notes-at-review + one-click link | Highest leverage on the core promise (a *connected* vault); reuses embedder; tiny surface | ★★★ | Low |
| **P0** | **A1** Quick-capture box | Removes the "must select first" friction — Memos' whole reason for 60k stars | ★★★ | Low |
| **P0** | **C2** Backlink index ("Linked mentions") | Table-stakes PKM feature; nearly free given existing edges | ★★☆ | Low |
| **P1** | **B1** Chunk-level embeddings | Sharpens linking *and* reconcile quality everywhere | ★★★ | Med |
| **P1** | **D2** Daily digest / Today | Turns the vault into a daily habit; pairs with calendar | ★★★ | Med |
| **P1** | **A2** Inbox-folder watcher | Unlocks phone/other-device capture without breaking offline | ★★☆ | Med |
| **P2** | **D1** Saved dynamic queries | Power-user planning; builds on `query.py` | ★★☆ | Med |
| **P2** | **A3** Local OCR capture | Big capability bump, but adds an optional heavy dep | ★★☆ | Med |
| **P2** | **B2** Deterministic rule engine | Predictable, cheap organization layer | ★★☆ | Med |
| **P2** | **C3** Offline interactive graph view | Nice-to-have visualization | ★☆☆ | Med |

**Suggested first slice:** the three **P0** items ship as one cohesive "the vault feels connected and
capture is frictionless" PR-set — each is small, constraint-safe, and reinforces grandplan's core thesis
rather than chasing a competitor's.

---

## 5. Constraint filter (explicitly rejected)

| Popular feature | Seen in | Rejected because |
|---|---|---|
| Cloud sync / hosted memory | mem0, supermemory, Khoj cloud | Network egress — **offline-only** |
| RSS auto-hoard, remote web archival | Karakeep, Joplin clipper | Fetches the internet — **offline-only** |
| Default cloud LLM (OpenAI/Claude) | AnythingLLM, Khoj, copilot | **Local LLM** non-negotiable |
| Real-time collaboration | AppFlowy, SiYuan | Out of scope; needs a server |
| E2E-encrypted multi-device sync | Notesnook | Out of scope; conflicts with plain-Markdown source of truth |
| Auto-mutating notes on import | (various) | Violates **lossless / verbatim** preservation |

---

## 6. Next step

Per the agreed plan, **stop here for review.** Open question for you: approve the **P0 first slice**
(C1 + A1 + C2) as the next PR-set, or re-prioritize? Once you pick, I'll write a SPEC for the chosen
items (contracts, edge cases, tests) before any implementation.
