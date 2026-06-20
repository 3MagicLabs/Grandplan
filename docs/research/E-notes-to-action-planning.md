# Research E — Notes → Action: Planning, Task Management, Agendas & Dynamic Queries

**Scope:** Open-source tools that turn notes/ideas into ACTION — task management, scheduling,
agendas/GTD, and dynamic query/view systems, especially those driven by Markdown notes or local AI.
**Excluded:** pure note capture, RAG chat apps, memory libraries, generic Obsidian AI plugins.

**Date:** 2026-06-19. **Star counts & licenses verified** via `gh api repos/OWNER/REPO --jq
'.stargazers_count, .license.spdx_id'` on that date. grandplan is **MIT** (`LICENSE`: 3MagicLabs 2026),
so AGPL/custom-licensed code must NOT be ported — only techniques/patterns may be borrowed.

## grandplan baseline (what it already has)

From `docs/adr/0004-planning-model-graph-projections.md`, `0008-event-sourced-progress-and-resources.md`,
and `src/grandplan/core/planner.py` / `query.py`:

- **One append-only knowledge graph; plans = deterministic projections** (never hand-maintained → never stale).
- **GTD horizons** per node: Masterplan / Goal / Project / Next-Action; `part_of` hierarchy.
- **Typed edges:** `depends_on`, `blocks`, `next`, `part_of`, `waiting_on`, `involves`, `builds_on`,
  `refines`, `supersedes`, `contradicts`, `relates` — already a real dependency graph.
- **Event-sourced status** (`NoteStatus`: DONE / SUPERSEDED / NEEDS_REVIEW, derived from event log; ADR-0008).
- **`due` dates + requirements[]**; a **Timeline projection** (`build_timeline`): ready / waiting / scheduled / conflicts.
- **"Now" list** of unblocked actionable tasks; "what moved" digest; **VaultQuery** read-only facade + MCP server.
- **Local LLM reconcile** (LlmContextualReconciler — whole-neighborhood RAG). Offline, 16GB, no-GPU, lossless.

### What grandplan LACKS (the gaps this research targets)

1. **Dynamic / saved / parameterized queries** over the vault (Dataview/SLIQ-style; VaultQuery has fixed methods, not a query language).
2. **A recurring "Today" / daily agenda digest** as a scheduled automation (Timeline is computed on demand, not pushed daily).
3. **Rich task states + transition workflows** (only DONE/SUPERSEDED/NEEDS_REVIEW; no IN_PROGRESS / WAITING / ON_HOLD lifecycle on tasks).
4. **Recurrence** (no repeating tasks / habits).
5. **Tunable urgency ranking** of the "now" list (no Taskwarrior-style scoring; ordering is structural only).
6. **SCHEDULED-vs-DEADLINE distinction** (single `due`; no "earliest start" date that hides a task until then).
7. **Inline, LLM-emittable task metadata grammar** in the markdown body (status/priority/recurrence signifiers a local LLM can write and parse).
8. **Multi-projection views** of the SAME task set (board / table / calendar / gallery).

---

## Tools surveyed (18, all verified)

### Markdown-native task & query systems

#### 1. Obsidian Tasks
- **URL:** https://github.com/obsidian-tasks-group/obsidian-tasks
- **Stars:** 3,815 · **License:** MIT (safe to study/port)
- **Techniques:**
  - **Inline markdown task syntax with emoji signifiers** — `- [ ]` items carry `📅 due`, `⏳ scheduled`,
    `🛫 start`, `🔼/🔽 priority`, `🔁 recurring`, `✅ done-date`, and **`🆔`/`⛔ blocked-by` dependencies** —
    all in the line, no sidecar DB. Fully offline, vault-portable, and **LLM-emittable**.
  - **6 status TYPES** (TODO, IN_PROGRESS, ON_HOLD, DONE, CANCELLED, NON_TASK) decoupled from the
    `[x]`/`[-]`/`[/]`/`[?]` *symbol*, so queries filter on semantic state, and **"Next Status Symbol"**
    chains drive multi-step workflows (todo → in-progress → done).
  - **Recurrence engine** — `🔁 every week` etc.; completing spawns the next instance (relative recurrence) → habits.
  - **Query language** in ```` ```tasks ```` blocks: boolean AND/OR/NOT, regex, date filters (`due today`,
    `happens before`), `sort by`, `group by`, `limit`, `show tree`; "Today" = `due today not done`.
- **Offline-fit:** Excellent; no AI. **grandplan lacks:** the inline signifier grammar, 6 task states, recurrence, the query block language.

#### 2. Obsidian Dataview
- **URL:** https://github.com/blacksmithgu/obsidian-dataview
- **Stars:** 9,081 · **License:** MIT
- **Techniques:**
  - **Live index + read-only query engine** over the whole vault (re-evaluates as metadata changes).
  - **Metadata model:** YAML frontmatter **+ inline `[key:: value]` fields** anywhere in body (attach `status`, `due`, `dependsOn`).
  - **DQL with 4 query types** (`TABLE`, `LIST`, `TASK`, `CALENDAR`) + composable `FROM` / `WHERE` / `SORT` /
    `GROUP BY` / `FLATTEN` / `LIMIT`. Today agenda: `TASK WHERE !completed AND due <= date(today) SORT due ASC`.
  - **`dataviewjs`** JS API (`dv.pages()`, `dv.table()`) for arbitrary views (e.g. dependency-graph traversal).
- **Offline-fit:** Excellent; no AI; **queries but never mutates** (relevant to grandplan's append-only writes). **grandplan lacks:** a vault query DSL of any kind.

#### 3. SilverBullet
- **URL:** https://github.com/silverbulletmd/silverbullet
- **Stars:** 5,486 · **License:** MIT (cleanest architectural match)
- **Techniques:**
  - **SLIQ (Space Lua Integrated Query)** — live embedded queries over the markdown space, rendered inline, auto-updating.
  - **First-class queryable `[ ]` tasks** assembled into cross-note agendas.
  - **Page Templates auto-triggered by path** (Daily Note / journal) → direct fit for daily-digest / Today pages.
  - **Space Lua** scripting for custom commands, widgets, computed views, and scheduling automations.
  - **AI via community plug** (`justyns/silverbullet-ai`): templated prompts + RAG + agents pointed at **Ollama / OpenAI-compatible** endpoints.
- **Offline-fit:** Excellent; local LLM opt-in. **grandplan lacks:** path-triggered daily templates, an embedded query+scripting layer.

#### 4. Logseq
- **URL:** https://github.com/logseq/logseq
- **Stars:** 43,463 · **License:** AGPL-3.0 (⚠ techniques only — do not copy code into MIT grandplan)
- **Techniques:**
  - **Block-level outliner** — every bullet is addressable; tasks/queries/refs attach at block granularity.
  - **Task markers** `LATER`/`NOW` (GTD) and `TODO`/`DOING`/`DONE` (+ `WAITING`/`CANCELED`), cycled by hotkey.
  - **`SCHEDULED:` / `DEADLINE:` org properties** power the built-in **Agenda/Journal** "what's due today" surface.
  - **Repeaters** (`.+1d`, `++1w`, `+1m`) auto-advance scheduled/deadline on completion.
  - **Journals (daily notes)** as default capture surface → natural idea→organized pipeline; **simple `{{query}}` + Datalog** advanced queries.
- **Offline-fit:** Excellent; AI via `ollama-logseq` plugin. **Closest end-to-end match** to grandplan's feature set. **grandplan lacks:** journals-as-agenda, scheduled/deadline split, repeaters.

#### 5. Obsidian Projects (⚠ archived May 2025)
- **URL:** https://github.com/marcusolsson/obsidian-projects
- **Stars:** 1,929 · **License:** Apache-2.0
- **Techniques:** **Four interchangeable views (Table / Board / Calendar / Gallery) over one note set**;
  data source = folder OR a Dataview query; frontmatter fields → columns/lanes/dates (write-back);
  **stores NO plugin config inside notes** (portability principle); create-from-view + templates.
- **Offline-fit:** Excellent; no AI. **grandplan lacks:** multi-projection views of one task set. (Ideas only — project is discontinued.)

### Plain-text / CLI GTD systems

#### 6. Taskwarrior
- **URL:** https://github.com/GothenburgBitFactory/taskwarrior
- **Stars:** 5,892 · **License:** MIT
- **Techniques:**
  - **Urgency coefficients (tunable polynomial):** numeric urgency = weighted sum — `+next` 15.0, due-proximity 12.0,
    blocking 8.0, priority H/M/L, scheduled 5.0, active 4.0, age 2.0, **minus** blocked −5.0 / waiting −3.0.
    Fully user-configurable per tag/project. **Deterministic, offline "what's next" ranker** — directly portable.
  - **States + date semantics:** `pending → completed/deleted`, plus `waiting` & `recurring`; `due:`, `scheduled:`
    (start; hides until then), `wait:` (hide until), `until:` (auto-expire).
  - **Recurrence via template+instance+mask** (`recur:weekly` + `due:`; hidden template spawns instances).
  - **Contexts (named saved filters) + custom declarative reports** (`report.NAME.columns/filter/sort`); `next` report = urgency-sorted agenda.
- **Offline-fit:** Excellent; no AI. **grandplan lacks:** urgency scoring, scheduled-vs-due, recurrence, saved-filter contexts.

#### 7. todo.txt-cli
- **URL:** https://github.com/todotxt/todo.txt-cli
- **Stars:** 6,123 · **License:** GPL-3.0
- **Techniques:** **One-task-per-line plain-text grammar** — `(A)` priority, `+project`, `@context`,
  creation/`x`-completion dates; `listpri`/`listcon`/`listproj` filtered views; `report.txt` trend counts;
  shell-script add-on plugin architecture. **The `@context`/`+project`/`(A)` token grammar is the canonical, LLM-friendly inline GTD encoding.**
- **Offline-fit:** Perfect (single text file). **grandplan lacks:** an inline `@context`/`+project` token grammar in note bodies.

#### 8. org-mode / nvim-orgmode (org-agenda)
- **URL:** https://github.com/nvim-orgmode/orgmode
- **Stars:** 3,787 · **License:** MIT
- **Techniques:**
  - **Custom TODO keyword workflows** (`TODO NEXT | DONE`, `|` separates active/done; fast-access keys).
  - **`SCHEDULED:` vs `DEADLINE:`** distinct semantics + `org_deadline_warning_days` lookahead.
  - **Repeaters** (`+1w`, warning offsets `-3d`) roll timestamps forward on completion.
  - **Agenda views = "Today" model:** `org_agenda_files` glob across many files → day/week agenda; sorting strategies;
    **`org_agenda_custom_commands`** = saved composite filtered views.
  - **Capture templates** (`%t` date, `%?` cursor, `datetree`) = the canonical manual notes→task pipeline; **tag inheritance** parent→child.
- **Offline-fit:** Excellent; no AI. **grandplan lacks:** multi-file agenda with saved custom commands, scheduled/deadline split, capture templates (its LLM replaces these).

### Self-hosted task/project apps (views, filters, dependencies)

#### 9. Super Productivity
- **URL:** https://github.com/super-productivity/super-productivity
- **Stars:** 20,174 · **License:** MIT
- **Techniques:** **Local-first source of truth + optional bring-your-own-sync** (Dropbox/WebDAV) — the
  offline-first architecture to emulate; **time tracking + estimates** in the task model; **"Work View" daily planner (Today)**
  pulling scheduled+due into one list; repeating tasks, sub-tasks, tags; **input→task ingestion** (Jira/GitHub/etc. → local actionable tasks).
- **Offline-fit:** Best-in-class single-user. **grandplan lacks:** a dedicated Today/Work view surface, time estimates.

#### 10. Vikunja
- **URL:** https://github.com/go-vikunja/vikunja (canonical; `vikunja/vikunja` 404s)
- **Stars:** 4,547 · **License:** AGPL-3.0 (⚠ techniques only)
- **Techniques:**
  - **Four pivot views over one model** — List / Table / Kanban / **Gantt**.
  - **Saved filters as first-class "virtual projects"** (navigable like real projects).
  - **Typed-edge relation graph** (not nesting): `subtask/parenttask`, `blocking/blocked`, `precedes/follows`,
    `related`, `duplicateof`, `copiedfrom` — **each auto-creates its inverse** (set one edge, both tasks reflect it).
  - State derived from Kanban position (move to "done bucket" → complete); start/end/due + reminders + recurrence + priority.
- **Offline-fit:** Yes (SQLite self-host). **grandplan note:** its edge set ≈ grandplan's, but **automatic inverse relations** and **saved-filter-as-project** are gaps; the inverse-edge idea fits an event-sourced substrate (record one relation event, derive both directions).

#### 11. Focalboard
- **URL:** https://github.com/mattermost/focalboard (now community-maintained)
- **Stars:** 26,251 · **License:** dual — binaries MIT / source AGPL-3.0 (hence `NOASSERTION`)
- **Techniques:** **Same dataset → Board / Table / Calendar / Gallery** (cleanest "one model, many projections" reference);
  user-defined custom card properties (Notion-style); **filter + group-by ANY property with unlimited saved views**;
  **board templates** (Project Tasks, Meeting Notes, Goals) = instant idea→structured-project.
- **Offline-fit:** Good (Personal Desktop edition runs fully local). **grandplan lacks:** templated project scaffolding, calendar/board projections.

#### 12. Planka
- **URL:** https://github.com/plankanban/planka
- **Stars:** 12,117 · **License:** custom "PLANKA Community License" v1.1 (fair-code, not OSI; ⚠ verify before any reuse)
- **Techniques:** Trello-style Projects→Boards→Lists→Cards (list position = workflow state); realtime WebSocket sync;
  cards with due dates/labels/markdown/attachments. Lighter; **no dependencies/Gantt/rich filters** — UX reference only.
- **Offline-fit:** Self-host (Docker+Postgres; heavier). Minimal relevance beyond clean Kanban UX.

### AI-driven & local-LLM planning/automation

#### 13. Khoj
- **URL:** https://github.com/khoj-ai/khoj
- **Stars:** 35,209 · **License:** AGPL-3.0 (⚠ techniques only)
- **Techniques:**
  - **Automations:** natural-language schedule → **compiles to a timezone-aware cron expression** → runs a saved
    query over your notes on interval → **delivers as a daily/weekly digest/newsletter.** The closest analog to a
    recurring "agent does X over my notes" job + daily agenda push.
  - **Custom agents** (persona + instructions + tool access scoped to your corpus); deep-research multi-step retrieval.
  - **First-class local-LLM:** Ollama, llama.cpp, any OpenAI-compatible local server; "offline chat stays completely private."
- **Offline-fit:** Strong (self-host, local models; 16GB recommended). **grandplan lacks:** the NL→cron→run-query→digest automation loop.

#### 14. Tracecat
- **URL:** https://github.com/TracecatHQ/tracecat
- **Stars:** 3,684 · **License:** AGPL-3.0 (⚠ techniques only)
- **Techniques:** **Triggers → actions** (webhook + scheduled/cron); **workflow-as-YAML over a DAG** ("YAML you can git diff",
  durable via Temporal); **templated expressions** pass trigger/prior-action output downstream; if/loops/scatter-gather;
  **AI agents as workflow steps with explicit tool approvals.** Overkill as a base, but the trigger→DAG→templated-action +
  agent-step-with-approval patterns map to "turn a note/trigger into an action."
- **Offline-fit:** Self-host (Docker/nsjail; heavyweight). Pattern reference only.

#### 15. AppFlowy
- **URL:** https://github.com/AppFlowy-IO/AppFlowy
- **Stars:** 72,606 · **License:** AGPL-3.0 (⚠ techniques only)
- **Techniques:** Database views **Grid / Kanban / Calendar** over one dataset (calendar = agenda); **first-class Ollama local AI**
  ("no data leaves your device", runs Llama 3.1 / DeepSeek R1 / Gemma 3 / Phi4); Rust+Flutter core. **Not markdown-native** (own block store) — diverges from the vault model.
- **Offline-fit:** Strong local AI. Reference for boards/calendar + local-AI UX, not storage.

#### 16. Reor
- **URL:** https://github.com/reorproject/reor
- **Stars:** 8,563 · **License:** AGPL-3.0 (⚠ techniques only)
- **Techniques:** Direct **Ollama** + Transformers.js local embeddings; **automatic note linking via vector similarity**;
  RAG Q&A + semantic search over a local markdown vault. **No task/agenda/dependency features** — reference for the local-LLM-over-vault retrieval layer (≈ grandplan's existing LlmContextualReconciler).
- **Offline-fit:** Excellent. Minimal planning relevance.

#### 17. AFFiNE
- **URL:** https://github.com/toeverything/AFFiNE
- **Stars:** 69,580 · **License:** NOASSERTION (custom; ⚠ verify)
- **Techniques:** **Edgeless/whiteboard "planning" mode** (same content as doc/page/infinite canvas → ideas→structure visually);
  embedded database blocks (table/kanban/calendar); Y.js CRDT local-first store. Heavyweight Electron — **caution for 16GB/no-GPU**; cloud-leaning AI. Borrow the edgeless-planning idea only.
- **Offline-fit:** Local-first storage; AI not local-first. UX idea only.

#### 18. Trilium (TriliumNext)
- **URL:** https://github.com/TriliumNext/Trilium
- **Stars:** 36,515 · **License:** AGPL-3.0 (⚠ techniques only)
- **Techniques:** **Attributes/relations on notes + a relational query layer** (strong note-relationship modeling);
  JS scripting + "render"/"book"/"calendar" view notes for custom dashboards/agendas/automations; hierarchical notes with cloning.
  **Not markdown-native.** Reference for the attribute/relation (relational-keystone) model, aligning with ADR-0008.
- **Offline-fit:** Self-host; no first-class local LLM. Pattern reference only.

---

## License summary (for code reuse vs. idea reuse)

| License | Tools | Reuse rule for MIT grandplan |
|---|---|---|
| **MIT** | Obsidian Tasks, Dataview, SilverBullet, Taskwarrior, nvim-orgmode, Super Productivity, Memos, Focalboard *binaries* | Safe to study **and port code** |
| **Apache-2.0** | Obsidian Projects (archived) | Safe to study and port (attribution) |
| **GPL-3.0** | todo.txt-cli | Copyleft — port with care; ideas safe |
| **AGPL-3.0** | Logseq, Vikunja, Khoj, Tracecat, AppFlowy, Reor, Trilium, Focalboard *source* | **Techniques/patterns ONLY — do NOT copy code** |
| **Custom / NOASSERTION** | Planka (fair-code), AFFiNE | Verify terms before any reuse; ideas safe |

---

## Synthesis — Top 5 techniques grandplan should borrow (offline-safe)

All five are 100% offline, MIT/permissively sourced (or pattern-only), and additive to the existing graph/projection model.

### 1. A read-only dynamic query DSL over the vault (Dataview/SLIQ-style)
- **What:** A small declarative filter/sort/group language (or parameterized query methods) on top of `VaultQuery` —
  e.g. `tasks where status != done and due <= today sort by due group by project`. Renders to a markdown view file or MCP tool result.
- **Why grandplan needs it:** VaultQuery has fixed methods, not a query language; every new view today requires code.
- **Source / license:** Obsidian Dataview (DQL), SilverBullet (SLIQ) — both **MIT** (safe to port the grammar).
- **Effort:** **M** — define a tiny grammar over already-indexed graph fields; pure/offline; reuse existing `VaultQuery` + `Planner` data.

### 2. Tunable urgency ranking for the "now" list
- **What:** Order unblocked actions by a deterministic polynomial: due-proximity + priority + `next`-edge + age,
  minus blocked/waiting. User-tunable coefficients in config.
- **Why:** The "now" list is structurally ordered only; users need a single "what should I do next" sort. No AI required.
- **Source / license:** Taskwarrior urgency model — **MIT** (directly portable; well-documented coefficients).
- **Effort:** **S** — a pure scoring function over existing Note fields + edges; add to the planner projection.

### 3. SCHEDULED-vs-DEADLINE split + recurrence
- **What:** Add an "earliest start" date (hide a task from "now" until then) distinct from `due`, plus inline repeaters
  (`+1w`) that, on a DONE event, append the next instance via the existing append-only event log.
- **Why:** Single `due` can't express "can't start before X"; no habit/recurring support today.
- **Source / license:** org-mode/nvim-orgmode (**MIT**) for scheduled/deadline + repeater syntax; Taskwarrior (**MIT**) for the template model.
- **Effort:** **M** — one new date field + a recurrence-on-completion projector that emits a creation event (fits ADR-0008 cleanly).

### 4. Daily "Today" agenda digest as a scheduled automation
- **What:** A recurring local job (Windows Task Scheduler / native) that runs the agenda query and writes/refreshes a
  `Today.md` (or journal page): overdue, due-today, ready-now (urgency-sorted), waiting-on. Optionally LLM-narrated.
- **Why:** Timeline is computed on demand; users want a pushed daily surface. Path-triggered Daily Notes are the proven pattern.
- **Source / license:** Khoj automations (NL→cron→run-query→digest; **AGPL — pattern only**) + SilverBullet/org daily templates (**MIT**).
- **Effort:** **S–M** — reuse `build_timeline` + technique #2; the scheduler trigger + a render-to-vault step. Stay offline (no email).

### 5. Inline LLM-emittable task grammar + richer task states
- **What:** Let the local LLM write/parse a compact inline grammar in note bodies — `@context`, `+project`, `[#A]` priority,
  `🔁`/`+1w` recurrence, and a 4–5 state lifecycle (TODO → IN_PROGRESS → WAITING → DONE/CANCELLED) decoupled from the symbol.
- **Why:** grandplan only has DONE/SUPERSEDED/NEEDS_REVIEW; an LLM-friendly inline grammar makes extraction lossless and round-trippable.
- **Source / license:** Obsidian Tasks (status types + signifiers, **MIT**), todo.txt-cli (`@context`/`+project`/`(A)`, GPL — grammar idea), Logseq markers (**AGPL — pattern only**).
- **Effort:** **M** — extend `NoteStatus`, define the grammar, teach the organizer/reconciler prompts to emit it, parse on ingest.

### Cross-cutting design notes
- **"Today"/agenda is universally just a query** (`due <= today AND not done`) — favor query-driven projections over hand-maintained lists (grandplan already does this; #1 generalizes it).
- **Two metadata-storage philosophies:** inline-in-body (Tasks/Dataview/todo.txt — diff-friendly, LLM-emittable) vs. frontmatter (Obsidian Projects — easy to query). grandplan's event log can carry structured fields; inline is best for round-tripping through the LLM.
- **Dependency/timeline modeling is a genuine cross-tool gap** — only Vikunja (typed edges + auto-inverse) and Obsidian Tasks (blocked-by) model it well. grandplan already has the richest edge set of any tool surveyed; its differentiator is the **local-LLM reconcile layer none of these have** — borrow Vikunja's **automatic inverse relations** to keep the event-sourced graph consistent.
