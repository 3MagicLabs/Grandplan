# C — Note-taking, Quick-Capture & Local-First PKM Apps

**Research slice:** CAPTURE UX and note ORGANIZATION (not AI) in open-source / local-first
note-taking and PKM apps.
**Date:** 2026-06-19. **Method:** WebSearch + WebFetch for techniques; `gh api` for every
star count and license (verified live, not from memory). Read-only research — no repo code modified.

## Why this matters for grandplan

grandplan today is a native-Windows, fully-**offline** second brain. Its only capture channel is a
**global hotkey that grabs the current text *selection*** (clipboard/UIA), which a local LLM then
organizes into atomic, lossless Markdown notes in an Obsidian vault. Non-negotiables: **offline-only,
lossless, local LLM, 16 GB no-GPU**.

The structural gap this research targets: grandplan can only capture **text you already selected in
another app**. It has **no quick-capture box for typed thoughts, no inbox, no daily-note sink, no
OCR/image, no voice, no web clipper, no mobile, and no typed/structured capture**. Every app below is
mined for **offline-safe** capture and organization techniques that respect those non-negotiables.

---

## Verified inventory (stars/licenses via `gh api`, 2026-06-19)

| App | Repo | Stars | License (SPDX) | Offline / local-first |
|---|---|---|---|---|
| Memos | usememos/memos | 60,922 | MIT | Self-host server (LAN/localhost) |
| MarkText | marktext/marktext | 57,570 | MIT | Yes (editor only) |
| Joplin | laurent22/joplin | 55,280 | NOASSERTION (AGPL/MIT mix) | Yes |
| SiYuan | siyuan-note/siyuan | 44,517 | AGPL-3.0 | Yes |
| Logseq | logseq/logseq | 43,463 | AGPL-3.0 | Yes |
| AppFlowy | AppFlowy-IO/AppFlowy | 72,606 | AGPL-3.0 | Yes |
| Trilium(Next) | TriliumNext/Trilium | 36,515 | AGPL-3.0 | Yes |
| Notesnook | streetwriters/notesnook | 14,165 | GPL-3.0 | Offline edit; account/sync-centric |
| Zettlr | Zettlr/Zettlr | 13,166 | GPL-3.0 | Yes (plain Markdown folder) |
| Anytype | anyproto/anytype-ts | 8,213 | NOASSERTION (custom ASAL) | Yes (P2P sync optional) |
| Dendron | dendronhq/dendron | 7,437 | Apache-2.0 | Yes (VSCode ext, plain MD) |
| Standard Notes | standardnotes/app | 6,516 | AGPL-3.0 | Offline edit; account/sync-centric |
| Athens | athensresearch/athens | 6,299 | NOASSERTION (EPL) | Yes — but **discontinued 2022** |
| org-roam | org-roam/org-roam | 5,976 | GPL-3.0 | Yes (plain-text `.org`) |
| Heynote | heyman/heynote | 5,305 | NOASSERTION (custom) | Yes |
| Notea | notea-org/notea | 2,146 | none (null) | **No** — server+S3, **archived** |
| Obsidian | (proprietary; obsidian-releases) | n/a (closed-source) | proprietary | Yes (this is grandplan's vault model) |
| Tana | (closed-source SaaS) | n/a | proprietary | Partial (capture offline only) |

Notes: Obsidian and Tana are **closed-source** (no app stars to report); included because their
capture/organization patterns are influential. The `obsidian-releases` ecosystem repo has 18,924
stars but is not the app source. Notea is **archived** and S3-backed — included only as an
anti-pattern. Athens is **unmaintained since 2022** — use Logseq as its live successor.

---

## Per-app findings

### 1. Memos — usememos/memos · 60,922★ · MIT
- **Capture:** A **persistent always-on quick-capture box** at the top of the timeline — type a
  thought and it persists instantly (lowest-friction pattern in this list). Drag-and-drop attach of
  images/audio/docs. Third-party mobile clients (Moe Memos) add share-sheet posting.
- **Organization:** Inline `#tag` as the *primary* axis (no folders), chronological private feed,
  full-text search, Markdown-native. Exports to Markdown/JSON/CSV.
- **Offline-fit:** Self-hosted; "zero external dependencies or cloud connections required" with a
  local SQLite/Postgres backend — but it is a **web/server app**, so capture needs the server
  reachable (localhost/LAN), not a single offline binary.
- **grandplan lacks:** The **persistent quick-capture box** as a primary surface — *author* a thought
  with no prior text selection. This is grandplan's single biggest UX gap.

### 2. MarkText — marktext/marktext · 57,570★ · MIT
- **Capture:** None beyond open-editor-and-type/paste. No hotkey, inbox, or clipper.
- **Organization:** File-tree (folders/files on disk). No links, tags, daily notes, or graph.
- **Offline-fit:** Fully offline, plain `.md` files, zero cloud — but an **editor, not a capture/PKM
  system** (less capable than grandplan for this slice).
- **grandplan lacks:** Nothing relevant. Included for completeness; **not a useful model**.

### 3. Joplin — laurent22/joplin · 55,280★ · NOASSERTION (AGPL/MIT mix)
- **Capture:**
  - **Built-in OCR, fully offline** (Tesseract.js): scans **PNG, JPEG, *and PDF*** to extract text;
    OCR'd text is added to full-text search. Verified at joplinapp.org/help/apps/ocr/: *"OCR too
    happens offline without the need for an internet connection and, more importantly, without the
    need to upload your private data to a third party cloud."* Printed text/screenshots only (no
    handwriting). Multi-language (EN/FR/DE/ES/zh-Hans), language packs downloadable.
  - **Web Clipper** (Chrome/Firefox): full page / simplified page / selection / screenshot /
    bookmark, bridged over **localhost** to the running desktop app (no cloud round-trip).
  - **Mobile share sheet** (Android + iOS): "Share with…" from any app creates a note.
- **Organization:** Nestable notebooks + tags + internal links + full-text search (now indexes OCR
  text); note templates; plugin Extension API.
- **Offline-fit:** Fully local-first (SQLite); sync is optional (Nextcloud/WebDAV/S3/filesystem/etc.).
  Capture, OCR, and search all work with no network. E2E encryption available.
- **grandplan lacks (biggest donor):** **Offline OCR of images + PDFs** (Tesseract is CPU-only, fits
  16 GB no-GPU); **localhost-bridged web clipper** (full page/selection/screenshot).

### 4. SiYuan — siyuan-note/siyuan · 44,517★ · AGPL-3.0
- **Capture:** Browser **web-clipper** extension (Chrome/Edge) preserving formatting+links;
  **Tesseract OCR** on images (offline, makes image text searchable); **daily notes**; PDF annotation
  linking back into the graph.
- **Organization:** Fine-grained **block-level references** + two-way links, **custom block
  attributes**, SQL query embeds, Markdown WYSIWYG, block export preserving refs/embeds.
- **Offline-fit:** "Complete offline usage" with a local-only mode; optional E2E-encrypted sync.
- **grandplan lacks:** **Offline OCR** (corroborates Joplin), **block-level references**, **custom
  block attributes**.

### 5. Logseq — logseq/logseq · 43,463★ · AGPL-3.0
- **Capture:** **Daily journal = default landing page / inbox** — the app opens in today's note, so
  capture is zero-friction with no destination decision. **Mobile share-sheet** appends shared
  text/URLs to the journal (documented reliability bugs when unsynced). Desktop quick-add shortcut;
  `[[page]]` and `#tag` create+link inline while typing. (A desktop *global hotkey* popup is a
  long-standing community request, not built-in.)
- **Organization:** Block-based **outliner** (every bullet is an addressable block), **block
  references** `((...))` + embeds, bidirectional links + backlinks, unified `#tag == page`, Datalog
  queries, whiteboards, flashcards.
- **Offline-fit:** Local-first plain Markdown/Org files; fully offline; sync optional.
- **grandplan lacks:** **Daily-note-as-inbox**, **block references** (lossless reuse without
  duplication — aligns with grandplan's lossless goal), **unified tag==page** capture.

### 6. AppFlowy — AppFlowy-IO/AppFlowy · 72,606★ · AGPL-3.0
- **Capture:** Command palette / slash commands inside docs; rich keyboard workflow; native mobile
  apps. No dedicated global quick-capture popup — capture happens inside the open workspace.
- **Organization:** Notion-style block model; **database views** (grid, board/Kanban, calendar) over
  the same notes; nested pages; tags via database fields.
- **Offline-fit:** Strong — runs 100% offline, self-hostable, optional local AI on CPU; sync optional.
- **grandplan lacks:** **Database/typed views** (board/calendar/table over the same notes) and a
  **command-palette / slash-menu** capture+navigation surface.

### 7. Trilium / TriliumNext — TriliumNext/Trilium · 36,515★ · AGPL-3.0
(legacy `zadam/trilium` now redirects here; sibling `TriliumNext/Notes` = 2,921★, AGPL-3.0)
- **Capture:** **Web Clipper** browser extension — text, **screenshots**, whole pages, short notes
  into Trilium. **Note hoisting** (focus a subtree). "Pocket Trilium" runs a full instance on phone
  with **full offline use** + sync.
- **Organization:** Deep **hierarchical tree**; **note cloning** (one note placed in many tree
  locations — single source, no duplication); **attributes** (labels/relations) for org, query,
  scripting; full-text search.
- **Offline-fit:** Desktop binaries (Win/Mac/Linux) run fully offline; optional self-hosted sync.
- **grandplan lacks:** **Note cloning / multi-placement** (one atomic note surfaced in many contexts
  without duplication — strong fit for a lossless atomic-note system), **attributes/labels** layer,
  screenshot-capable clipper.

### 8. Notesnook — streetwriters/notesnook · 14,165★ · GPL-3.0
- **Capture:** **Web Clipper** (selection / full-page / **screenshot** modes) connecting to the local
  web app; **mobile share extensions** (Android+iOS); **capture-time auto-routing** — clips can be
  auto-filed into a chosen notebook/tag from the clipper itself.
- **Organization:** Notebooks + nested topics, tags, internal links, full-text search.
- **Offline-fit:** Local-first offline edit/create; zero-knowledge E2E encryption; sync is the default
  account-centric path (self-host possible). Leans on an account; **not** a plain-Markdown vault.
- **grandplan lacks:** **Capture-time auto-routing to a destination** (user picks notebook/tag at
  capture); full-page/screenshot clipper modes.

### 9. Zettlr — Zettlr/Zettlr · 13,166★ · GPL-3.0
- **Capture:** In-editor typing only (no separate capture channel) — but **Zettelkasten ID
  generation** (`Cmd/Ctrl+L` inserts a configurable-pattern ID at cursor, recognized in filename and
  body).
- **Organization:** Wiki-links `[[...]]`, **implicit links** (shared-keyword based), backlinks,
  hashtag tags + tag cloud + tag manager (rename/replace across vault). Workspace = any plain-Markdown
  folder.
- **Offline-fit:** Fully offline/local-first; no account, no cloud, no built-in sync. **Closest
  structural match to grandplan's vault model.**
- **grandplan lacks:** **Zettelkasten ID generation + filename/body recognition** (stable atomic-note
  identity / dedup anchor), **vault-wide tag-management** tooling, implicit keyword links.

### 10. Anytype — anyproto/anytype-ts · 8,213★ · NOASSERTION (custom Any Source Available License)
- **Capture:** Mobile apps optimized for capture/quick review; "objects" created from any context;
  widgets. Recommended split: mobile to capture, desktop to organize.
- **Organization:** Everything is a typed **Object**; custom **Types** + **Relations** (typed
  properties); **Sets** (saved queries) and **Collections** (manual groups); bidirectional links +
  graph. The closest mainstream analog to **Tana supertags** — typed capture with structured fields.
- **Offline-fit:** Excellent — local-first, on-device encryption, fully offline; optional **P2P
  encrypted sync** (no required central cloud).
- **grandplan lacks:** **Typed objects + relations** — a "this is a `#person`/`#task`/`#source` with
  fields" layer. grandplan captures untyped text only; a lightweight front-matter `type:` + typed
  relations would be a major organization upgrade, fully offline.

### 11. Dendron — dendronhq/dendron · 7,437★ · Apache-2.0
- **Capture:** **Lookup-driven quick capture** — a modal that **defaults to a scratch note**: start
  typing to capture instantly, or type a name to create/navigate (capture + navigation in one fuzzy
  interface). Built-in **journal** + **scratch-note** commands; VSCode snippets for templated insert.
- **Organization:** Dot-delimited filenames (`area.topic.subtopic`) encode hierarchy; lookup
  navigates the tree; schemas auto-suggest/enforce hierarchy; wikilinks + backlinks + hierarchical
  links. Plain Markdown + YAML frontmatter.
- **Offline-fit:** Fully local-first ("serves your notes without ever having to pull from a server");
  plain Markdown; runs as a VSCode extension.
- **grandplan lacks:** **Scratch-note / journal quick-capture command** (typed entry point, not just
  clipboard selection); **hierarchical dot-path naming + schemas** layered on atomic notes.

### 12. Standard Notes — standardnotes/app · 6,516★ · AGPL-3.0
- **Capture:** Quick note creation + file/image/document attachments (all E2E-encrypted).
- **Organization:** Unlimited tags, **nested tag hierarchies**, native nested folders, full-text
  search. Local editor extensions run on-device.
- **Offline-fit:** Offline read/edit/create, sync on reconnect; **account-based sync** (cloud or
  self-host). Stores **encrypted blobs, not plain Markdown** — weaker fit for grandplan's lossless-
  Markdown-vault non-negotiable.
- **grandplan lacks:** **Nested tag hierarchies** as a complementary organization axis.

### 13. Athens Research — athensresearch/athens · 6,299★ · NOASSERTION (EPL) · **discontinued 2022**
- **Capture:** Roam-style instant typing into **daily notes**; `[[ ]]` inline page create/link;
  `(( ))` block references.
- **Organization:** Block-based outliner, bidirectional links, backlinks pane, graph, daily-note
  inbox.
- **Offline-fit:** Was local-first desktop; now effectively dead. **Reference design only — use
  Logseq as the live successor.**
- **grandplan lacks:** **Daily-note-as-default-inbox** + **block references** (both covered by Logseq).

### 14. org-roam / Emacs org-capture — org-roam/org-roam · 5,976★ · GPL-3.0 ⭐ canonical pattern
(org-capture ships with Emacs/Org core, GPL)
- **Capture:** **`org-capture` (global key `C-c c`)** opens a **template picker** from anywhere → pick
  a template → a small buffer pops up → type → `C-c C-c` files it. **Capture templates** define a key,
  a destination file+heading (e.g. `Inbox.org`), and a body skeleton with placeholders (`%?` cursor,
  `%U` timestamp, `%a` link-to-context). This is the **instant typed capture to an inbox** pattern.
  org-roam adds `org-roam-dailies` (daily-note capture) and typed literature/concept templates.
- **Organization:** **Refile** (`C-c C-w`) moves inbox items to their permanent home later — "capture
  now, organize later." Zettelkasten backlinks via org-roam.
- **Offline-fit:** Perfect — 100% local plain-text `.org`, no network ever; capture is instant by
  design.
- **grandplan lacks (HIGH PRIORITY):** **Capture templates** (multiple typed targets: idea / task /
  source / quote, each routing to a section with a skeleton); **inbox + later refile** ("land now,
  sort later"); a **quick-capture box for *typed* input** with timestamp + source-context link.

### 15. Heynote — heyman/heynote · 5,305★ · NOASSERTION (custom)
- **Capture:** **Global hotkey** raises a scratchpad instantly from anywhere (unreliable on Wayland —
  Electron limit). One persistent **scratch buffer** as a frictionless inbox; `Ctrl/Cmd+Enter` starts
  a new block; global search; "archive" rolls scratch content into a new buffer and resets it.
- **Organization:** Buffer split into **blocks**, each with its own language (Markdown/JSON/JS/…) for
  highlighting + auto-format. Multiple named buffers. Deliberately minimal — no links/tags/graph.
- **Offline-fit:** Fully offline desktop (Mac/Win/Linux); local files; optional file-sync.
- **grandplan lacks:** The **scratch-buffer inbox** (always-available hotkey dump of *typed* text,
  not requiring a prior selection). Validates grandplan's hotkey instinct but shows the missing piece:
  capture of typed thoughts, not just selections.

### 16. Notea — notea-org/notea · 2,146★ · no license · **archived** (anti-pattern)
- Self-hosted Notion-like editor backed by **S3 object storage**; requires a running server + network.
  **Disqualifying** for grandplan's offline-only / no-server non-negotiables. Included only as a
  contrast.

### 17. Obsidian (closed-source; storage model grandplan already uses)
- **Capture:** Official open-source **Web Clipper** (browser ext + iOS share sheet) clips
  highlights / full page / reader-mode selection to the vault as Markdown, can target daily/weekly
  notes, configurable hotkeys; **command-palette** capture; **global/assignable hotkeys**; built-in
  **Daily Notes** inbox; community QuickAdd plugin adds a quick-capture popup.
- **Organization:** `[[wikilinks]]` + backlinks pane, graph, tags + folders, block references
  (`^block-id`), aliases, frontmatter properties.
- **Offline-fit:** Fully offline — plain Markdown on disk; clipper saves locally and works without
  internet; sync is a paid optional add-on. **This is exactly grandplan's vault model.**
- **grandplan lacks:** A **(local) web clipper**, **command-palette capture**, OCR via clipper,
  mobile share-sheet — the most natural gaps given grandplan already writes an Obsidian vault.

### 18. Tana (closed-source SaaS; supertag pattern)
- **Capture:** **Global Clipper** (desktop hotkey → modal overlay to paste, apply a supertag, set
  fields, @mention without leaving the app); voice/camera/media on mobile; capture destination
  selectable (Today / Tomorrow / **Inbox** / Pinned); Daily page auto-created as catch-all inbox.
- **Organization:** **Supertags** apply a type + a field schema to *any* node, **retroactively** —
  capture freely first, structure later. Typed knowledge graph over an outliner.
- **Offline-fit:** Closed SaaS; mobile capture works offline but it is not local-first.
- **grandplan lacks:** **Supertag-style typed capture** + **inbox destination chooser at capture
  time** + **"capture now, type later"** (retroactive structure). All offline-implementable; one of
  the highest-value organization borrows.

---

## Synthesis — Top 5 offline-safe capture-UX + organization techniques to borrow

Ranked by leverage × fit with grandplan's offline-only / lossless / local-LLM / 16 GB-no-GPU
non-negotiables. Each respects offline-only.

### 1. Quick-capture box for *typed* thoughts (not just text selection)
- **What:** A hotkey-raised popup that accepts free typed text (with a timestamp + optional
  source-context link), in addition to today's selection-grab. Closes grandplan's single biggest UX
  gap: you can only capture text you already highlighted elsewhere.
- **Sources / licenses:** Memos (MIT, persistent box) · Heynote (custom, hotkey scratchpad) ·
  Emacs org-capture (GPL, template buffer) · Obsidian QuickAdd.
- **Offline:** Pure-local — no network. **Effort: LOW.** A small Qt dialog feeding the existing
  `CaptureCoordinator.submit()`; the coordinator's serialize/observe contract already exists.

### 2. Inbox + "capture now, organize later" (decouple capture from the local LLM)
- **What:** Land raw captures in an **inbox** (a folder or a daily note) immediately, and run the
  local-LLM organize/reconcile step **asynchronously or on demand** (org-capture's *refile*). Today
  grandplan runs the 3B LLM **synchronously at capture time** — the worst moment to wait on CPU
  inference on a 16 GB no-GPU box (this exact coupling caused the OOM cascade behind ADR-0006).
- **Sources / licenses:** Emacs org-capture/refile (GPL) · Logseq journals (AGPL-3.0) · Tana Inbox.
- **Offline:** Fully offline; in fact *reduces* the offline compute burden at capture time.
  **Effort: MEDIUM.** Add an inbox sink + a deferred "organize inbox" pass; reuses existing
  organize/reconcile pipeline.

### 3. Offline OCR of images + PDFs (Tesseract, CPU-only)
- **What:** Capture text from screenshots / images / PDFs locally, then feed the extracted lossless
  text into the existing organize pipeline. Directly fills grandplan's explicit "no image/PDF/OCR"
  gap and extends capture beyond text.
- **Sources / licenses:** Joplin (Tesseract.js, **verified offline**, images **and PDF**) · SiYuan
  (AGPL-3.0, Tesseract on images).
- **Offline:** Tesseract is CPU-only and fully offline (fits 16 GB no-GPU). **Effort: MEDIUM.** Bundle
  a Tesseract binding (e.g. `pytesseract`/`tesseract`) as an optional `[ocr]` extra; OCR output is
  just text into the existing capture path.

### 4. Typed / supertag capture (a lightweight "type + fields" layer on atomic notes)
- **What:** At (or after) capture, tag a note with a **type** (`idea` / `task` / `source` / `person`)
  carrying a small field schema, written as frontmatter — Tana's "capture freely, structure later."
  This is a major organization upgrade over untyped atomic notes and gives the LLM + graph
  projections structured handles.
- **Sources / licenses:** Anytype (typed Objects + Relations, custom OSS license) · Tana supertags
  (closed, pattern only) · Standard Notes nested tags (AGPL-3.0).
- **Offline:** Pure metadata in Markdown frontmatter — fully offline, lossless. **Effort: MEDIUM.**
  Define a small typed-frontmatter schema + capture-time type picker; the LLM can also infer/propose
  the type (fits the existing reconcile flow).

### 5. Note cloning / block references (lossless reuse without duplication)
- **What:** Surface one atomic note in multiple contexts via **transclusion / block references**
  rather than copying it. A direct expression of grandplan's **lossless** non-negotiable — reuse
  without duplicating content, and edits stay single-source.
- **Sources / licenses:** Trilium note cloning (AGPL-3.0) · Logseq/SiYuan block references
  (AGPL-3.0) · Obsidian block refs (proprietary, pattern only).
- **Offline:** Plain Markdown embed/link syntax — fully offline. **Effort: MEDIUM-HIGH.** Needs stable
  block/note IDs (pair with Zettlr-style ID generation, GPL-3.0) and graph-projection support for
  transclusion edges.

### Honorable mentions (offline-safe, lower priority)
- **Daily-note-as-inbox** (Logseq/Obsidian/org-roam-dailies) — a date-stamped page as the always-open
  capture sink; trivial in grandplan's Obsidian vault. Pairs with #2.
- **Command-palette / lookup-default-to-scratch capture** (Obsidian; Dendron, Apache-2.0) — a
  keyboard-driven capture+navigate entry point.
- **Capture-time auto-routing to a destination** (Notesnook, GPL-3.0) — user (or LLM) picks the
  notebook/tag at capture.
- **Local web clipper bridged over localhost** (Joplin/Trilium/Obsidian) — full-page/selection/
  screenshot capture to the local vault; **higher effort** (browser extension + localhost service)
  and partial dependence on the page being open, so ranked below the above.

### Explicitly NOT recommended
- **Notea** — archived, server+S3, online-only: violates offline-only.
- **Standard Notes** as a *storage* model — encrypted blobs, not lossless Markdown (borrow only its
  nested-tag idea).
- **Notesnook / Outline / Karakeep** as *architectures* — account/server/crawler-centric; mine them
  only for individual capture-channel ideas (clipper modes, auto-routing).
- **MarkText** — editor only; less capable than grandplan for this slice.

---

## Verification notes
- All star counts and licenses re-verified directly via `gh api repos/OWNER/REPO` on 2026-06-19
  (Joplin 55,280 / Memos 60,922 / Logseq 43,463 / SiYuan 44,517 / AppFlowy 72,606 / Anytype 8,213 /
  org-roam 5,976 / Zettlr 13,166 / Dendron 7,437 / Heynote 5,305 — all confirmed).
- Joplin offline OCR (images **and PDF**, no internet, Tesseract.js) verified at
  https://joplinapp.org/help/apps/ocr/ (direct quote captured above).
- Obsidian and Tana are closed-source (no app stars); Athens is discontinued (2022); Notea is
  archived — all flagged inline.

**Sources:** GitHub API (stars/licenses); joplinapp.org/help/apps/ocr & /clipper; usememos.com/features;
obsidian.md/help/web-clipper; github.com/siyuan-note/siyuan; TriliumNext cloning + web-clipper docs;
docs.zettlr.com; wiki.dendron.so; systemcrafters.net org-roam; outliner.tana.inc (supertags/clipper);
heynote.com/docs; help.notesnook.com; standardnotes.com; appflowy.com.
