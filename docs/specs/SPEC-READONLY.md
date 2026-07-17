# SPEC-READONLY — `gui --read-only`: browse a vault that cannot be modified

## 1. Why

The tray app exists to *write* — hotkey capture is its whole point. But the thing users increasingly
do with a full vault is **read** it: chat with it, follow links, look at the graph. That is a
strictly-safe activity being performed by a process that holds a live writer, a registered global
hotkey, and (with `--serve`) an HTTP intake. The risk is not hypothetical: a stray hotkey press, a
phone POST, or an accidental Approve all write, and an append-only log means a mistake is a permanent
event rather than an undo.

There is also a specific, sharp case this closes. `--embeddings` must match how a vault was built,
and a mismatch is silent (`_dot` zips a 384-dim query against a 256-dim stored vector with
`strict=False` and compares noise). Diagnosing that means *running the app against the real vault
with the flag flipped* — and the moment you capture during that test, you have written a wrong-
dimension vector into the vault permanently. A read-only mode makes that diagnosis free.

## 2. Contract

`grandplan gui -o <vault> --read-only` launches the tray app with **every vault write path sealed**.

Guaranteed: for the lifetime of the process, no bytes are written into `<vault>` and no events are
appended to its index.

## 3. Constraints

1. **Structural, not cosmetic.** Hiding buttons is not the mechanism — the ports themselves are
   replaced with proxies that raise. A future code path that tries to write fails loudly instead of
   quietly succeeding, so this guarantee does not decay as the app grows.
2. **Loud, not silent.** A blocked write raises `VaultIsReadOnly`, is logged with a traceback, and is
   surfaced to the user. Read-only must never look like a write that worked.
3. **Refuse, don't ignore.** `--read-only` with a flag that only makes sense for writing (`--serve`,
   `--auto-approve`, `--enrich`) is a contradiction in the user's intent, not something to silently
   resolve. Exit 1 and say which flag conflicts.
4. **Reading is unaffected.** Chat, `/focus`, `/graph`, clickable sources, and the grounding pane all
   work exactly as they do normally. A degraded read-only mode would not get used.
5. **The index is part of the vault's state.** A capture appends to `index.jsonl` before anything is
   rendered, so "the vault is not modified" must cover the index, not just the `.md` files.
6. **The log is not.** `<index>/logs/grandplan.log` is diagnostic output about the process, not vault
   content, and is what makes constraint 2 checkable. It keeps being written.

## 4. What is sealed

| Path | Normally | Under `--read-only` |
|---|---|---|
| Global hotkey capture | registered listener thread | never registered |
| Phone `/capture` (`--serve`) | HTTP server thread | refused at startup (conflict) |
| Enrich pass (`--enrich`) | post-save background writes | refused at startup (conflict) |
| Auto-approve (`--auto-approve`) | commits without review | refused at startup (conflict) |
| Chat `/plan` → Approve | writes project note + edges | Approve hidden; drafting still allowed |
| Chat `/improve` → Approve | appends an edit event | Approve hidden; drafting still allowed |
| `write_projections` | re-renders Plan.md/graph.json | never called (nothing commits) |
| `NoteRepository` mutators | append events | raise `VaultIsReadOnly` |
| `VaultWriter.write` | writes a `.md` | raises `VaultIsReadOnly` |

**Drafting stays on.** `draft_plan` / `draft_improvement` are read-only — they call the model and
return a proposal; only Approve writes. Seeing what the vault *would* propose is exactly the kind of
low-risk exploration this mode is for, so the draft renders and the Approve button is simply absent.

## 5. Edge cases

- **A write attempt that slips through** — raises, is logged with a traceback, and reaches the user
  as a visible message. It does not crash the app.
- **A vault that does not exist** — read-only must not create it. Scaffolding (`--init`) is a write;
  it conflicts.
- **`--read-only` with `--hotkey-combo`** — not a conflict. The combo is inert because no listener is
  registered; refusing would punish a user for leaving a flag in their shortcut.
- **Opening Obsidian** (`--open`, clickable sources) — Obsidian is a separate process and the user
  may edit there. This mode constrains *grandplan*, not the user; the guarantee is about what this
  process writes.

## 6. Verification

The seal is proven by unit tests against the proxies, not by inspecting the GUI: every mutator on
`ReadOnlyRepository` raises, every reader delegates, and `ReadOnlyVaultWriter.write` raises. The
conflict matrix is proven at the CLI boundary. The Qt shell stays `pragma: no cover`.
