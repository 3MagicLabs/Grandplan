# grandplan — MVP Research

> Deep research under borromeo's research discipline (multi-engine search, primary-source
> verification, fail-closed on unverifiable claims). Confidence + open questions stated
> explicitly; citations inline.
>
> **Date:** 2026-06-15 · **Status:** research complete for MVP scoping → informs `SPEC.md`.

## 0. MVP shape (current, after user simplification)

A **native Windows desktop** "second brain." The MVP is a **selection-driven capture
pipeline**, not a bulk file processor and not a web app:

1. User **selects text in ANY app** (the primary content is `.txt`, but capture is system-wide).
2. User **triggers capture** (global hotkey / tray button).
3. The selection is **stored verbatim (lossless)** and sent to a **local LLM** that parses,
   enhances, and organizes it into a structured note/plan.
4. User **reviews and approves**.
5. On approval it becomes a **node in a semantically meaningful, Obsidian-like graph**,
   linked to related notes; saved in a **portable, structured format** reusable by other
   software the user builds later.

**Hard constraints:** native desktop (NOT web) · works across any app · fully offline ·
never loses/distorts the original selection (top correctness gate) · modest hardware
(≤16GB RAM, integrated graphics) · runs on **Windows**.

> Because we capture *selected text* (not pixels), **no OCR is needed** — simpler/more reliable.
> A small local LLM on a *short selection* (a few seconds) is fine on modest hardware.

**Deferred (post-MVP):** social-media auto-capture, Instagram/LinkedIn ingestion, LinkedIn
connections/job analyzer, voice module, images/OCR, cross-device sync, bulk-file animated parse.

## 0.1 Decision update (2026-06-15): Obsidian is the vault + viewer

**We do NOT build a custom graph UI.** grandplan writes clean Markdown into an **Obsidian
vault**; Obsidian provides the graph, navigation, and cross-platform viewing. This
**supersedes §2g (custom PySide6 graph) and the graph parts of §3/§4 below.**

- **grandplan = capture (any app) → local-LLM organize (lossless) → human approve →
  write a clean, atomic, well-linked Markdown note into the vault → dedup against existing notes.**
- **Vault (folder of `.md` + `[[wikilinks]]`) = the user-facing source of truth** and the
  portable, reusable format for future software. **SQLite (+ sqlite-vec) becomes an internal
  index** (embeddings, similarity, dedup, provenance), derived from / rebuildable from the vault.
- **grandplan stays a Python desktop app that writes *into* the vault — NOT an Obsidian plugin**
  (a TS plugin couldn't capture from any app, and would break borromeo's Python gate).
- **The only grandplan UI is minimal:** a tray app + a small review/approve dialog. No graph to build.
- **Cleanliness is OUR job, not Obsidian's** (the anti-"second jumbled mess" requirements):
  (1) atomic notes; (2) consistent frontmatter schema + verbatim original preserved;
  (3) semantic `[[links]]` to related notes so nothing floats; (4) **dedup/merge before create**
  (most important); (5) auto-maintained Map-of-Content/index notes = the "grand plan" surface;
  (6) human approval gate. citation: Obsidian vault = local plain-Markdown, https://help.obsidian.md
- **Low lock-in:** if Obsidian disappears, the `.md` files remain fully usable.

## 1. Prior art — what exists, what to learn, the gap

| Tool | Offline? | Auto-organizes selected/messy text? | Preserves originals | Graph viz | Learn from it |
|---|---|---|---|---|---|
| Obsidian + **Smart Connections** | Yes (local embed model, no API key) | **No** — only *suggests* related notes | Yes (MD) | Yes | Local-embedding-on-device; "map of meaning" UX. citation: github.com/brianpetro/obsidian-smart-connections |
| Logseq / Anytype / **SiYuan** | Yes, local-first | No (manual) | Yes | Yes | Block/outliner atomic-unit & object models; SiYuan = OSS architecture |
| **rahulnyk/knowledge_graph** | LLM-dependent | Yes — concepts→edges via LLM | input kept | Yes (pyvis) | **Reference impl** of text→concept-graph |
| **mjm.local.docs** | Yes | ingest+embed (search, not reorg) | Yes | No | Pluggable embeddings + SQLite vector store |
| Clipboard/capture tools (TurboClip, "Capture") | Yes | No (just store/OCR) | Yes | No | Global-hotkey capture patterns; Capture uses PyQt + OCR. citation: github.com/Yusuf-YENICERI/Turbo-Clip |
| Valorune / Atlas / Atomic / Constella | claimed | claimed | claimed | claimed | ⚠️ marketing/SEO pages only — **unverified**; inspiration not evidence |

**The gap grandplan fills (well-supported):** existing tools split into (a) **manual**
organizers, (b) semantic **search/suggest** over notes you already wrote, and (c) **capture
tools** that just store/OCR text. **None** combine *system-wide selection capture* → *local-LLM
lossless organization* → *human approval* → *Obsidian-like semantic graph*, fully offline.
grandplan is essentially **"a global capture hotkey fused with a local-AI organizer + graph."**

## 2. Techniques by component (options → recommendation → confidence)

### 2a. System-wide selection capture (Windows)
- **Clipboard method (universal default):** global hotkey via `pynput.GlobalHotKeys` or the
  `keyboard` lib (background thread, works regardless of focus) → simulate Ctrl+C →
  read clipboard (`pyperclip`/`pywin32`). Works in any app that supports copy.
  **Mitigation:** save & restore the user's prior clipboard so we don't clobber it.
  citation: pynput.readthedocs.io; pypi.org/project/keyboard
- **UI Automation enhancement:** Windows `ITextProvider::GetSelection` reads the selection
  *directly* without touching the clipboard, but only where the app implements `ITextProvider`
  (Python via `comtypes`/`uiautomation`). citation: learn.microsoft.com ITextProvider::GetSelection
- **Recommendation (high confidence):** clipboard-with-save/restore as the robust universal
  path; try UIA first where available and fall back to clipboard. Behind a `Capturer` interface.

### 2b. Local LLM (organize/enhance a short selection, offline)
- **Runtime:** **Ollama for Windows** (silent install, system tray, auto GPU→CPU fallback,
  fully offline) — ~10 tok/s for a 7B-Q4 model on a modern CPU w/16GB; budget ~0.6GB/1B params
  at q4. For short selections this is responsive. citation: caffeinecreations Ollama-on-Windows; localaimaster Ollama requirements
- **Self-contained alt:** `llama-cpp-python` embeds the runtime in-process (no external service)
  — better for a single distributable, heavier to package with a model file.
- **Structured output:** **GBNF grammar** (llama.cpp `json-schema-to-grammar`) or Ollama
  `format=json` constrains output shape. **Caveat:** not 100% guaranteed valid (token cutoff)
  → always **validate the JSON and retry/repair**. citation: github.com/ggml-org/llama.cpp grammars README; til.simonwillison.net llama-cpp-python-grammars
- **Recommendation (medium-high):** behind an `Organizer` interface; MVP uses Ollama (fastest to
  ship) with a small model (e.g. Llama-3.2-3B / Qwen2.5-3B Q4); GBNF/format=json + schema
  validation. Model swappable; embeddable runtime is the graduation path.

### 2c. Embeddings + semantic linking (offline, cheap on CPU)
- `all-MiniLM-L6-v2` (~22.7M params, ~80MB; hundreds–thousands short sentences/sec on CPU;
  Smart Connections ships a ~25MB quantized build). Used to link a new note to related notes.
  Alternatives `bge-small`, `gte-small`. citation: sbert.net efficiency; github.com/brianpetro/obsidian-smart-connections

### 2d. Lossless, intent-preserving store (TOP correctness requirement)
- Store every captured selection **verbatim** with provenance: source app/title, timestamp,
  and — for `.txt` — original character offsets. All derived structure (LLM-enhanced note,
  graph node, edges) **references** the original; the original is **append-only, never mutated**.
  **This is our own design (not found pre-solved) → must be the first thing we TDD** with a
  round-trip "no original char lost or altered" test. Confidence: medium (design sound; ours to prove).

### 2e. Clustering / topic grouping (grows later)
- Start simple: cosine-similarity threshold + community detection over note embeddings; graduate
  to HDBSCAN/`BERTopic` as volume grows (HDBSCAN over-marks noise on tiny sets, default
  `min_topic_size=10`). Keyphrases via `KeyBERT`/`YAKE`. citation: maartengr.github.io/BERTopic

### 2f. Storage
- **SQLite** single local file: notes (verbatim + provenance), graph nodes/edges, embeddings via
  **`sqlite-vec`** (pure-C, Python binding, successor to sqlite-vss; **pre-v1 → wrap behind a
  repository interface**, swappable for faiss/chroma). citation: github.com/asg017/sqlite-vec
- **Portable export** (the "reusable by other software" requirement): plain Markdown + a JSON
  graph (nodes/edges) — open formats, no lock-in.

### 2g. Native desktop GUI + Obsidian-like graph (NO web)
- **PySide6** (Qt) native app; **QGraphicsView/QGraphicsScene** for the interactive node graph.
  Libs to learn from / reuse: **NodeGraphQt-PySide6**, **SpatialNode**, Qt's Diagram Scene
  example. `PyQtGraph` if plots needed. System tray via `QSystemTrayIcon`.
  citation: doc.qt.io QGraphicsView; github.com/C3RV1/NodeGraphQt-PySide6; github.com/SpatialGraphics/SpatialNode
- UI surfaces: a **review/approve panel** (original selection ┃ LLM-organized note) and the
  **graph** (approved node animates in, linked to related nodes). The elaborate live parse-overlay
  is dropped (simplification); a light "node joins graph" animation is optional.

## 3. Architecture — ports & adapters

```
            ┌──────────────── Windows adapters (run/integration-test on Windows) ───────────────┐
 any app →  │  Capturer (hotkey + clipboard/UIA)   PySide6 GUI (review/approve + graph)   LLM    │
            └─────────────┬───────────────────────────────┬──────────────────────────────┬──────┘
                          │ selected text                  │ approve/edit                  │ Ollama/llama.cpp
            ┌─────────────▼────────────────────────────────▼──────────────────────────────▼──────┐
 WSL2-gated │  CORE (platform-agnostic, borromeo-gated, TDD):                                      │
 core       │   ingest(verbatim+provenance) → organize(LLM via Organizer port) → embed → link →   │
            │   project(Markdown doc + graph nodes/edges) → lossless-verify                        │
            │   Repository port → SQLite (+ sqlite-vec)                                            │
            └─────────────────────────────────────────────────────────────────────────────────────┘
```

- **Core** = pure Python, no Windows/UI/LLM deps directly — only **ports** (`Capturer`,
  `Organizer`, `Embedder`, `Repository`). Fully unit-testable + **borromeo-gated in WSL2**.
- **Adapters** = thin Windows implementations of the ports; integration-tested on Windows.
- This satisfies CS130 information-hiding/low-coupling and keeps the gate honest (the risky
  logic — losslessness, organization, linking — is all in the gated core).
- **Acceptance test (user's bar):** select text in Notepad → hotkey → LLM-organized note shown →
  approve → node appears in graph linked to related notes; **round-trip proves zero original
  text lost/altered**; data exported as Markdown + JSON graph.

## 4. Roadmap

- **Phase 0 — core, headless (here in WSL2, TDD, gated):** `Organizer`/`Embedder`/`Repository`
  ports + fakes; ingest-with-provenance; lossless round-trip test **first**; organize→project to
  Markdown + JSON graph; embedding-based linking. *This is where the real risk lives.*
- **Phase 1 — Windows shell:** PySide6 tray app + global hotkey + clipboard capture (save/restore);
  review/approve panel; SQLite persistence.
- **Phase 2 — graph UI:** QGraphicsView Obsidian-like graph; approved node joins, linked by similarity.
- **Phase 3 — real LLM adapter:** Ollama/llama-cpp-python `Organizer` with GBNF/JSON-schema + validation; small model.
- **Phase 4 — polish/export:** UIA capture enhancement; Markdown/JSON export for downstream software.
- **Deferred:** social/Instagram/LinkedIn capture, voice, images/OCR, cross-device.

## 5. Feasibility verdict

**Feasible on the stated constraints.** Global-hotkey clipboard capture is a proven Windows
pattern; PySide6+QGraphicsView gives a native (no-web) Obsidian-like graph; Ollama/llama.cpp run
small models offline on CPU and respond fast on short selections; SQLite+sqlite-vec is a portable
local store. **Genuine risks:** (1) the **lossless guarantee** (our design — TDD it first), and
(2) **organization *quality*** from a small local model (validate JSON, keep human approval in the
loop). The WSL2-dev / Windows-run split is handled by ports-and-adapters.

## 6. Coverage report

**Searched:** general web + dork-style queries, GitHub (web), MS Learn primary docs, Qt docs,
llama.cpp/pynput primary docs, Reddit/HN/blogs, PyPI. ~24 queries + 2 primary fetches across all
sub-questions; saturation on the items below.

**Well-supported (verified):** Smart Connections = suggest-only (the gap); clipboard+hotkey capture
& UIA `GetSelection`; PySide6/QGraphicsView native graph; Ollama-on-Windows offline + ~10 tok/s 7B-Q4;
GBNF/JSON-schema structured output (not 100% → validate); sqlite-vec local but pre-v1; embeddings cheap on CPU.

**Still uncertain / prove during build (flagged, not asserted):**
- **Offset-level lossless provenance** — our design; prove by test.
- Capture reliability across *specific* apps (clipboard vs UIA coverage) — verify on real apps in Phase 1.
- Organization *quality* from a 3B-class local model on messy selections — empirical; human approval mitigates.
- Exact tok/s + embedding throughput on the user's specific CPU — benchmark in Phase 0/3.
- Packaging a self-contained Windows app w/ bundled model (Ollama dependency vs embedded llama-cpp) — decide at Phase 3/4.
- Marketing-page tools (Valorune/Atlas/Atomic/Constella) — unverified; revisit only if inspectable.

## 6.1 Community workflows & techniques (GitHub · Reddit · web)

**Closest prior art — Reor (github.com/reorproject/reor):** a private, **fully-offline** AI note
app that **chunks + embeds every note** into a local vector DB (LanceDB) and **auto-links related
notes by similarity**, with a local LLM via Ollama and an Obsidian-like Markdown editor; built on
llama.cpp + Transformers.js + LanceDB; Mac/Linux/Windows. Validates grandplan's embeddings→auto-link
core on modest local hardware. **Gap vs Reor (our differentiation):** Reor is its *own* app — it
does **not** do system-wide capture-from-any-app, does **not** emphasize **verbatim lossless
provenance**, and does **not** write into *your* Obsidian vault or project a **plan**.

**Obsidian + local-AI ecosystem (reuse patterns):** AI Tagger Universe (Ollama auto-tagging),
Automatic Linker, Smart Connections (local embeddings, graph+list), Smart Second Brain / Copilot
(offline RAG, local vector store), Khoj (self-hostable AI second brain), llm-wiki-local ("drop notes
→ AI extracts concepts → auto-links and grows"). The "local embeddings + Ollama on localhost:11434"
pattern is well-trodden and reliable.

**Capture pipeline (Windows):** dominant pattern = **global hotkey → save clipboard (ClipboardAll)
→ Ctrl+C → read clipboard → process → restore clipboard** (exactly our US-1 + save/restore).
AutoHotkey is a viable alternative to a Python hotkey listener for the capture adapter (obsidian-inbox
uses an AHK script → quick-capture).

**Dedup is a recognized need (validates US-6):** Smart Dedupe Pro is built around a **"review-first"
workflow — "similar notes are candidates, not conclusions"** — exactly our merge-with-approval design.
Obsidian has Merge Notes / built-in Note Composer / Advanced Merger for consolidation.

**Methodologies for note→plan:** the community converges on **PARA** ("where does this belong?"),
**GTD** ("what do I do next?"), **Zettelkasten** (atomic, linked notes), and **MOCs** (index/front-page
notes); **Tasks + Dataview** turn checkboxes + frontmatter into a "command center." Directly supports
US-8: typed notes + dependency edges + status/priority frontmatter → a generated Plan MOC.

**Pain points / lessons (what to AVOID — verified themes):** collecting-for-collecting,
**over-organizing**, **never reviewing**, and **app-sprawl chaos**. Consensus: keep it **simple**, tie
notes to **actionable** work, make **review** part of the daily flow. → grandplan implications:
one-hotkey low friction, force **actionability** (plan projection), enforce **dedup** (no pile-up),
keep **human-in-the-loop review**.

**Text→graph extraction (learnable):** ai-knowledge-graph (LLM → Subject-Predicate-Object triples →
interactive graph) and Graphiti (real-time KG, local Ollama/llama.cpp) show how to derive typed edges
with a local model — useful for our typed-edge/plan-DAG work.

## 7. Sources
- Smart Connections — https://github.com/brianpetro/obsidian-smart-connections
- sqlite-vec — https://github.com/asg017/sqlite-vec
- knowledge_graph (text→graph) — https://github.com/rahulnyk/knowledge_graph
- mjm.local.docs — https://github.com/markjackmilian/mjm.local.docs
- SiYuan — https://github.com/siyuan-note/siyuan
- Turbo-Clip (capture pattern) — https://github.com/Yusuf-YENICERI/Turbo-Clip
- Windows UIA ITextProvider::GetSelection — https://learn.microsoft.com/en-us/windows/desktop/api/UIAutomationCore/nf-uiautomationcore-itextprovider-getselection
- pynput keyboard / GlobalHotKeys — https://pynput.readthedocs.io/en/latest/keyboard.html
- keyboard lib — https://pypi.org/project/keyboard/
- PySide6 QGraphicsView — https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QGraphicsView.html
- NodeGraphQt-PySide6 — https://github.com/C3RV1/NodeGraphQt-PySide6
- SpatialNode (Qt node editor, PySide6) — https://github.com/SpatialGraphics/SpatialNode
- Ollama on Windows (offline) — https://caffeinecreations.ca/blog/running-a-local-llm-on-windows-with-ollama/
- llama.cpp grammars (GBNF) — https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md
- llama-cpp-python grammars (Simon Willison) — https://til.simonwillison.net/llms/llama-cpp-python-grammars
- Sentence-Transformers efficiency — https://sbert.net/docs/sentence_transformer/usage/efficiency.html
- BERTopic — https://maartengr.github.io/BERTopic/algorithm/algorithm.html
- Reor (local AI note app, auto-link) — https://github.com/reorproject/reor
- Awesome Obsidian AI Tools — https://github.com/danielrosehill/awesome-obsidian-ai-tools
- Khoj (AI second brain) — https://github.com/ai-khoj/khoj
- obsidian-inbox (AHK quick-capture) — https://github.com/tmfelwu/obsidian-inbox
- AutoHotkey Clip() (capture+restore) — https://www.autohotkey.com/board/topic/70404-clip-send-and-retrieve-text-using-the-clipboard/
- Smart Dedupe Pro (review-first dedup) — https://smartconnections.app/smart-dedupe/releases/1-0/
- Obsidian Merge Notes — https://www.obsidianstats.com/plugins/merge-notes
- PARA+GTD+Zettelkasten in Obsidian — https://www.techedubyte.com/obsidian-pkm-para-gtd-zettelkasten-guide/
- "The Trap of PKMs" (pain points) — https://josiahalenbrown.substack.com/p/the-trap-of-pkms
- ai-knowledge-graph (LLM triples→graph) — https://github.com/robert-mcdermott/ai-knowledge-graph
- Graphiti (real-time KG, local LLM) — https://github.com/getzep/graphiti
