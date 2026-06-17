# 6. A testable CaptureCoordinator: serialize captures, surface progress

- **Status:** Accepted
- **Date:** 2026-06-16

## Context

The tray GUI (`app/gui.py`, issue #7) wired capture → organize → embed → reconcile → review →
commit as **closures inside `run_app()`**, all `# pragma: no cover`. Field use surfaced three
defects, all rooted in that untestable orchestration:

1. **No serialization / re-entrancy.** Heavy work (a local LLM call + transformer embeddings) ran
   **synchronously on the Qt main thread**, including the modal review dialog. A modal `exec()`
   spins a *nested* event loop, so the 150 ms `QTimer` that drained the trigger queue could
   **re-enter `do_capture()` while the previous capture was still on the stack** — stacking
   multiple concurrent LLM pipelines. The same `drain()` also **coalesced** queued triggers into a
   single capture, so back-to-back hotkeys silently **dropped** captures. The result was the worst
   of both: work was lost *and* could pile up.
2. **No observability.** Between the hotkey and the review dialog there was **no progress signal of
   any kind** (the first capture can take tens of seconds: model load + CPU inference). Users
   assumed a hang and pressed again → triggering (1).
3. **Untestable.** Because the logic lived in `pragma: no cover` closures, none of this was covered
   by the gate. On a 16 GB / no-GPU machine running the default **7B** model under an
   **uncapped WSL2 VM**, stacked pipelines exhausted host RAM → WSL teardown + host freeze.

## Decision

**Extract Class:** introduce a Qt-free **`CaptureCoordinator`** (`app/coordinator.py`) that owns the
capture lifecycle, and make the GUI a thin binding to it.

- **Single-flight serialization.** One daemon **worker thread** drains a **bounded queue
  (`max_pending=1`)**. At most one capture is in flight and one queued; further `submit()`s are
  **rejected with a visible "busy" status** — never silently dropped, never stacked. Because
  captures are serialized, only **one** `ollama.chat` runs at a time, so Ollama can't fan out into
  parallel model runners (a key part of the memory blow-up).
- **Observability via Observer.** The coordinator emits a `CaptureStatus(stage, detail)` for every
  stage (`CAPTURING → ANALYZING → AWAITING_REVIEW → COMMITTING → SAVED/DISCARDED/EMPTY/FAILED →
  IDLE`) through an injected `on_status` callback, and logs each stage. The GUI maps these to the
  tray tooltip/notifications; tests assert the exact sequence.
- **Off the UI thread.** All heavy work (LLM, embeddings, vault write, plan/graph projection via the
  injected `after_commit` hook) runs on the worker thread. The review **decision** is the only
  main-thread step: it is an injected `review(state) -> bool`, which the GUI marshals to the main
  thread (blocking-queued signal); tests pass a plain function.
- **Fault isolation.** One capture's failure is caught, reported as `FAILED`, and the worker keeps
  serving (one bad capture can't kill the tray app).

Reuses the already-tested `app/review` controller (`start_review`/`approve`/`discard`) — the
coordinator adds *serialization + observability*, not new pipeline logic.

## Consequences

- The orchestration is now **fully unit-tested in WSL2** with fakes — no Qt/Windows needed — so the
  gate governs it. The concurrency contract (serialize, bound, reject-when-busy, fault-isolate) is
  pinned by tests, including a deterministic re-entrancy test.
- **Default model lowered to `llama3.2:3b`** (~2 GB vs ~5 GB) to honor the "runs on 16 GB, no GPU"
  constraint; 7B remains opt-in via `--model`. Memory-safe WSL2 operation is documented
  (`docs/WINDOWS.md`: `.wslconfig` cap) as a hard prerequisite.
- Future richer progress (per-token LLM streaming) or a different review UI bind to the same
  `on_status`/`review` seams without touching the coordinator.
