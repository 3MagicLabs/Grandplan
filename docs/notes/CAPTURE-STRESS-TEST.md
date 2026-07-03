# Capture stress-test scenario (#7)

Manual scenario for the Windows capture path. Run after changes to `adapters/capture.py`,
`app/coordinator.py`, or the GUI wiring. Expected observations rely on the always-on file log
(`<index>/logs/grandplan.log`, #5) and the tray.

## Setup

```powershell
python -m grandplan.cli gui -o <vault> --debug   # console + file logging
```

Confirm at startup: `log: <path>` printed; log contains `hotkey listener registered on …`.

## 1. Rapid-fire captures (queue + debounce)

Select text in any app; press the hotkey **5× within ~2 s**.

- Log shows `hotkey fired` per press, with at least one `hotkey fire ignored (debounced …)`.
- No crash; captures are processed one after another (queue serializes); when the buffer fills,
  the tray shows the REJECTED_BUSY status instead of stacking work.

## 2. Empty-selection storm (stale-clipboard race)

Copy some text manually (so the clipboard is NON-empty), then click on empty desktop (nothing
selected) and press the hotkey 3×.

- Every attempt reports "no text was selected" — the pre-existing clipboard content is **never**
  captured as a note (clear-before-copy semantics; pinned by
  `test_no_fresh_selection_never_captures_stale_clipboard`).
- Afterwards your manually-copied text is still on the clipboard (restore semantics).

## 3. Terminal capture (Ctrl+C is not copy)

Focus a terminal window with text "selected" by the cursor and press the hotkey.

- No note is created from stale clipboard; status reports empty. (Ctrl+C in a terminal is SIGINT,
  so `send_copy` populates nothing; the cleared clipboard makes that unambiguous.)

## 4. Dead hotkey listener (detection + surfacing)

Simulate: launch with a hotkey another running app already grabbed exclusively, or kill the
listener thread's backend (e.g. temporarily uninstall `pynput` in the venv and launch).

- The tray shows a **warning notification** ("capture hotkey inactive …") and the tooltip changes.
- The log contains `hotkey listener crashed…` (with traceback) or `hotkey listener stopped…`.
- The tray's **Capture now** still works — only the global hotkey is down.
- Exit-path behavior is pinned hermetically by the `run_hotkey_listener` tests in
  `tests/adapters/test_capture.py` (crash, quiet stop, no-callback, failing-callback).

## 5. Crash trace (any thread)

With the console closed, any unhandled exception on any thread must appear in
`<index>/logs/grandplan.log` with a full traceback and the thread's name (#5).

## Pass criteria

All five sections observed as described, zero silent failures: every abnormal event has BOTH a
log line and (where user-relevant) a visible tray signal.
