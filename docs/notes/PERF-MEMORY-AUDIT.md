# Performance & Memory Audit — 2026-07-05

Five parallel audit passes over `src/grandplan/` (model lifecycle, data growth, I/O
amplification, threading, algorithmic scaling), each verifying findings directly against the
code. Findings below are deduplicated and ordered by priority; file:line references are from
commit `55ef684`. Context: the 2026-07-05 OOM incident (Windows killed Ollama mid-request,
taking terminals/WSL down) — grandplan.log showed chat + capture hitting Ollama concurrently
with both models pinned resident.

## P0 — Correctness bugs (fix before anything else)

**P0.1 Chat "Approve" writes race the capture worker — single-writer invariant broken; real
data-loss window.** `chat_window.py:311` runs the approved apply on its own thread;
`gui.py:462-473` close over the SAME `repo`/`originals`/`vault_dir` the coordinator worker uses;
`kb_chat.py:245-254` then does `repo.add_note` + `write_projections` with no lock. ADR-0006's
"single writer" (`coordinator.py:202-204`) holds only for captures. Concrete hazard: the note is
added to the repo before its `.md` is rendered; if the worker's `reproject`
(`gui.py:377-380`, `reconcile_deletions=True`, `protect_ids` = captured note only) runs in that
window, `_tombstone_user_deletions` (`project.py:316-333`) **permanently tombstones the
just-approved plan note as a "user deletion."** Also: interleaved JSONL appends
(`note_store.py:87-90`), unsynchronized dict mutation (`repository.py:20-30`), and two threads
rewriting `Plan.md`/`graph.json` at once. *Fix: route `apply_plan`/`apply_improve` through the
coordinator worker (a `submit_write(fn)` job), or one repo+vault lock shared by both.*

**P0.2 With the `[index]` extra, GUI captures fail outright — sqlite used cross-thread.**
`vec_index.py:58` connects on the main thread with `check_same_thread` defaulted to True; the
worker's first `most_similar`/`_index` call raises `sqlite3.ProgrammingError`, which the broad
catch (`coordinator.py:397-399`) turns into FAILED for every capture. Worse: in `add_note` the
JSONL append (`vec_index.py:100`) lands before `_index` (`:102`) raises — persisted note,
FAILED report. *Fix: `check_same_thread=False` + an internal lock around `_db`, or funnel all
index access through the worker (same fix as P0.1).*

**P0.3 `up --hotkey`: two unserialized writers + full LLM pipeline inside the keyboard hook.**
The `/capture` lock (`cli.py:1046`) covers only HTTP threads; the hotkey path
(`cli.py:870-885` → `_capture_to_vault`) writes the same index/vault with no lock — and runs
~25-45s of LLM work synchronously on the pynput hook callback (`capture.py:229-234`), lagging
input system-wide and risking silent hook removal. *Fix: share the lock; make the hotkey
callback enqueue-only.*

**P0.4 A torn `index.jsonl` line bricks startup.** Kill/quit mid-append (worker join gives up
after 5s while an LLM call can hold 180s) leaves a partial line; `_load`
(`note_store.py:45-51`) raises `JSONDecodeError` and the app won't launch until hand-repaired.
*Fix: skip-and-quarantine undecodable trailing lines with a warning.*

**P0.5 Cross-process writers are uncoordinated.** The `up` banner (`cli.py:798`) invites a
`grandplan mcp --write` process against a vault `up` is actively writing; two processes append
to the same JSONL with divergent in-memory views and both run `write_projections`. *Fix: file
lock around append+projection, or document `--write` as exclusive.*

## P1 — Per-capture amplification (the dominant scaling problem; 3 auditors converged)

> **Status: the WRITE amplification (P1.1 + P1.4) is FIXED.** Every projection write now goes
> through `core.fs.write_text_if_changed`, which skips a write when the file is byte-identical to
> what's on disk — so a capture over an unchanged vault rewrites **zero** files and never bumps an
> mtime (no OneDrive re-upload storm). Proven by `test_repeat_projection_over_unchanged_vault_
> rewrites_nothing`. The READ amplification (P1.2 redundant `build_plan` recompute, P1.3 deletion
> reconciliation opening every `.md`) is **still open** — captures are much lighter but not yet O(1).

**P1.1 Every commit rewrites the ENTIRE vault.** `gui.py:377-380` (`after_commit`) →
`write_projections` → `write_notes` loops ALL notes (`project.py:257-313`), reads each file
(`vault.py:88`) and rewrites it unconditionally (`vault.py:101` — no content comparison, even
byte-identical), plus graph.json, Plan.md, Masterplan.md, Timeline.md. ~2N reads + N writes +
3 globs per capture; the just-committed note is written twice. At 1k notes ≈ 2,000 file ops per
hotkey press; at 10k ≈ 20,000. Inside OneDrive every mtime bump re-uploads the vault per
capture. *Fix (highest leverage, one behavior): skip writes whose rendered content is unchanged
(the file is already read); longer term, re-render only the touched note + link-neighbors.*

**P1.2 Derived state is replayed O(N·E), ~6-7× per projection.** `repository.py:119-136`
(`current_note`) makes three full event-log scans per note; `history_of` (`:142-143`) a fourth
inside `write_notes` (`project.py:309`). Per projection, `build_plan` alone runs 3-4×
(plan/masterplan/timeline/agenda: `project.py:244-251`, `planner.py:268,297`), plus
`export_graph` and `_tombstone_user_deletions` each re-derive `current_notes()`. ≈20·N·E event
touches per capture — ~10⁹ at 10k notes / 20k events. The code predicts the fix
(`repository.py:120-121`). *Fix: memoize a note_id→(status, edits, resources) index invalidated
on append; build the Plan once per projection and share it.*

**P1.3 Deletion reconciliation opens every `.md` per commit.** `project.py:327` reads 512 bytes
of every vault file each capture (`vault.py:328-335`); `_remove_renamed_orphans`
(`project.py:344-348`) reads heads again. With OneDrive Files On-Demand this can hydrate
cloud-only placeholders en masse. *Fix: cache the id→path map grandplan itself wrote; reconcile
from directory listing.*

**P1.4 graph.json fully parsed for its ownership check, then fully rewritten, per capture.**
`project.py:402-409` `json.loads` of the whole multi-MB file to find the `_grandplan` sentinel;
`graph.py:50-52` re-dumps with indent=2. `write_guide` (`project.py:159-163`) rewrites identical
bytes every projection too. *Fix: sentinel in the head + skip unchanged writes (the
`write_obsidian_config` pattern at `project.py:112-113` already does this right).*

**P1.5 `up`/phone captures re-open ALL persistent state per capture.** `cli.py:847-848` and
`cli.py:1075-1076` rebuild `JsonlNoteRepository` (full JSONL parse incl. every embedding vector)
+ `JsonlOriginalStore` + a fresh sqlite connection with full `_sync` (`vec_index.py:146-170`)
per hotkey press / HTTP POST. The GUI does this once per process (`gui.py:198-200`). *Fix: open
once in `_serve_all`/`_run_hotkey`, reuse under the existing lock.*

## P2 — Model-memory residency (the OOM incident class)

**P2.1 `keep_alive="30m"` hardcoded on every Ollama call — overrides the user's server-side
setting.** `_ollama.py:92,126`. Request-level keep_alive beats `OLLAMA_KEEP_ALIVE`, so users
cannot shorten residency; after one chat turn + one capture, both models (~19GB with 14b) sit
pinned 30 minutes. No `GRANDPLAN_KEEP_ALIVE` knob exists (unlike `GRANDPLAN_NUM_CTX`). *Fix:
env knob, default lower; `keep_alive=0` for the infrequent KB model.*

**P2.2 Chat and capture LLM calls run concurrently, unguarded.** Every chat turn spawns a free
daemon thread (`chat_window.py:241,253,263`) calling Ollama while the capture worker may be
mid-organize — exactly the two-models-resident path of the incident. Multiple chat windows
multiply it. *Fix: a process-wide LLM gate (semaphore) shared by all `_ollama` call sites, or
default the GUI chat's model to the capture model.*

**P2.3 Fallback loads the second model precisely under distress.** `kb_ask.py:130-146`,
`kb_chat.py:295-306`: the `except Exception` treats a 180s timeout like "model missing" and
re-runs the full prompt on the fallback model — loading ~9GB more while the machine is already
thrashing. *Fix: fall back only on not-found/connection errors; timeouts and parse failures
degrade to retrieval-only.*

**P2.4 Whisper model constructed from scratch per voice note.** `voice.py:65` and `:87` build
`WhisperModel(...)` inside every `transcribe` call (the object caches only the model *name*);
`/capture` voice posts each pay a full ctranslate2 load, and concurrent posts each load their
own copy outside the organize lock (`http_intake.py:203` thread-per-request;
`capture_intake.py:157-163` transcribes before the lock). *Fix: module-level lazy singleton
keyed by model name (the `st_embedder._lazy_encode` pattern); serialize transcription.*

**P2.5 One-size `num_ctx=8192` for every call.** Titles-only placer prompts and one-line
detector prompts allocate the same 8192-token KV as full organizes; on a 14b chat model that KV
is multi-GB. The `num_ctx` parameter exists but no call site uses it (`_ollama.py:69`).
*Fix: smaller ctx for detectors/placer — but keep values stable per model (option changes force
an Ollama reload).*

**P2.6 Organizer strict-retry doubles timeout cost.** `ollama_organizer.py:191-212` retries the
full prompt after ANY failure including a 180s timeout → up to 6 min per capture, ×16 queue =
silent 96-minute backlog. *Fix: retry only on parse/refusal errors.*

## P3 — Startup, memory footprint, and vault-size scaling

**P3.1 Startup replay is quadratic.** `note_store.py:53-85` replays each status/edit/resource
record through the guarded mutators, each doing full scans of events-so-far (O(E²)); edges via
`add_edge`'s `in self._edges` list scan (O(E²)). 10k events ≈ 10⁸ ops before the app is usable.
*Fix: trusted bulk-load mode that appends directly; `set[Edge]` beside the list.*

**P3.2 Embeddings as boxed-float tuples ≈ 8-12KB/note, triplicated.** `repository.py:21` RAM
tuples (~12.3KB at 384 dims vs 1.5KB as float32) + JSON text in index.jsonl (~7KB/line, all
parsed at startup) + float32 in vec.db. 10k notes ≈ 123MB RAM + ~80MB file; 100k ≈ 1.2GB.
*Fix: `array('f')`/binary sidecar; skip the RAM copy when the vec index is healthy.*

**P3.3 Every Original ever captured (incl. discarded) loaded into RAM forever.**
`store.py:52-65` keeps full verbatim text of all-time captures; `write_notes` needs one at a
time. *Fix: id→offset index, read on demand.*

**P3.4 Status events embed the full capture text.** `review.py:293-297` puts the whole
triggering capture into `NoteEvent.detail` — duplicated in RAM, JSONL, and every History
render. *Fix: cap with `snippet_of` (exists at `coordinator.py:141`).*

**P3.5 Brute-force `most_similar` is pure-Python O(N·d), 2-4× per capture — the DEFAULT
install.** `repository.py:148-163`; no numpy anywhere in src. ~0.5s/query at 10k notes; sqlite-vec
(`[index]`) fixes it but is optional and degrades silently (`vec_index.py:33-46`). *Fix: make
`[index]` a default dep (after P0.2!) or `array('f')` math; surface degradation in doctor/tray.*

**P3.6 `report.missing_links` is O(N²) dynamic regex.** `report.py:73-78` + `densify.py:35`
compile a fresh pattern per note-pair (regex cache thrashes past 512 titles); runs after every
CLI organize/regenerate/doctor. Tens of seconds at 1k notes, hour-scale at 10k. *Fix: one
combined alternation pass per body.*

**P3.7 `regenerate` holds ~3 full indexes + all originals in RAM; `_replay_history` is
O(events²).** `cli.py:369,412,329-341`. *Fix: events-only loader; per-note event index.*

**P3.8 sqlite-vec first build: full-table MAX + fsync per row.** `vec_index.py:135,144` — 10k
notes ≈ minutes on first open. *Fix: track max rowid; one transaction.*

**P3.9 No embedding batching.** `st_embedder.py:46` encodes one text per call; regenerate over
10k originals ≈ 5-8 min vs ~30s batched. *Fix: `embed_many` on the port.*

## P4 — Session hygiene and servers

**P4.1 Chat windows leak.** `gui.py:441,478` — closed windows (each with a ChatSession +
transcript) are retained for the process lifetime. Caution: the leak currently makes late
worker-thread signal emits safe (bridge parented to a never-destroyed window) — fix both
together (prune on `finished` once no thread is in flight). `TranscriptLog` is also unbounded
and re-renders full HTML per turn (`chat_window.py:49-59,209-211`).

**P4.2 HTTP intake: no socket/read timeouts, unbounded threads.** `http_intake.py:203` — headers
read pre-auth with no timeout (slowloris pins a thread); `rfile.read(length)` can block forever
on an under-sending client; no `server_close()` after shutdown. Body-size gating is already
excellent (pre-read caps). *Fix: `_Handler.timeout = 30`; `server_close()` in finally.*

**P4.3 `/capture` lock held across LLM calls.** `cli.py:1067-1080` — burst phone posts park
handler threads indefinitely. *Fix: `acquire(timeout)` → 503 busy.*

**P4.4 Misc small leaks/costs.** `folder_watch.py:76` `seen` grows forever + full re-list/resolve
per 5s tick; `directive.py:164-176` all-time directives in RAM; edge `in edges()` fresh-tuple
copies (`repository.py:64-65`, `enrich.py:83,92`); new `ollama.Client` per call
(`_ollama.py:84,118`); ST first-use can download ~90MB mid-capture with no timeout
(`st_embedder.py:45`); attach-name dedup O(K) stat probes (`cli.py:1055-1057`); "Capture now"
menu item blocks the Qt main thread ~0.7s (`gui.py:482`); quit can stall 5s on the review
handshake (`gui.py:358-367`); `up` lacks the GUI's crash diagnostics (`cli.py:1474` only).

## Verified-good patterns (do NOT "re-fix")

Bounded capture queue (16) + visible REJECTED_BUSY; enrichment backlog capped 256, deduped,
idle-priority, opt-in; chat history capped 6 turns; all prompt/UI text snippet-capped; universal
180s LLM timeout; centralized Ollama options (`_ollama.py`) with the `GRANDPLAN_NUM_CTX` knob;
one embedder instance per process; HTTP pre-body-read auth/size gating with constant-time token
compare; append-only JSONL stores with no-op guards; index outside the vault (OneDrive-aware);
sqlite-vec as rebuildable cache with honest fallback; tombstone-set fix in `most_similar`; heap
toposort in planner; `protect_ids` guard against self-tombstoning; no-zombie worker restart
logic; diagnostics hooks that chain.

## Recommended fix order

1. **P0.1 + P0.2 together** — make the coordinator worker the only thread touching
   repo/originals/vault (fixes the data-loss race AND the sqlite cross-thread break).
2. **P1.1 + P1.4** — skip unchanged file writes (one behavior, kills most I/O and the OneDrive
   churn per capture).
3. **P2.1 + P2.3** — `GRANDPLAN_KEEP_ALIVE` knob + fallback only on not-found (the OOM class).
4. **P1.2** — memoized derived-state index + one Plan per projection (the CPU cliff).
5. **P0.3/P0.4/P1.5** — `up`-path lock + enqueue-only hotkey + torn-line tolerance + open-once.
6. **P2.4** (Whisper singleton) before promoting voice capture; the rest opportunistically.
