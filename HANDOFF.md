# HANDOFF — grandplan

> Working state for picking up in a fresh session (keeps multi-file feature work out of an
> exhausted context window, per the engineering rules).

## Where things stand (main)

The MVP is complete, gated, and running on the user's native-Windows machine. Recent merged work:

- **#36** stability: `CaptureCoordinator` (serialized single-worker, bounded queue, progress events, off-UI-thread) — fixed the OOM/freeze.
- **#37** US-10 richer reconciler (builds_on/refines/supersedes/contradicts) + consistency-by-projection (ADR-0007).
- **#38** hardening: QAS-1 offline-egress test, vault-clobber guard, US-9 portability, Windows quickstart + `run.bat`.
- **#39** fix: `_ReviewRequest` hashable (GUI capture crash).
- **#40** clean note filenames (id → frontmatter/aliases, alias-based links), valid Obsidian tags, richer frontmatter.
- **#41** index moved OUT of the (OneDrive-)synced vault to `~/.grandplan/<vault>` (`GRANDPLAN_HOME` overridable) + one-time migration.
- **#42** wired `LlmRelationshipClassifier` into the GUI with two-tier linking (`llm_top_k`).

Gate: **342 tests, 97% coverage**, all green; CI mirrors it.

## Operational notes for the user's machine
- Run on **native Windows** (Python 3.12 from python.org, not Anaconda), `--llm --embeddings`, model `llama3.2:3b`.
- **Cap WSL** (`~/.wslconfig` `memory=4GB`) or it competes with the Windows app for 16 GB → freeze.
- `git pull` then relaunch (editable install; no reinstall needed).

## Next: build the "git for ideas" program — see **ADR-0008** (event-sourced progress + resources)

User approved building the **whole** program (status updates + detail edits + history + resource
embedding + artifact-attach flow). Execute the PRs in ADR-0008 order, each TDD + gated + reviewed +
CI-merged (the loop used for #36–#42):

1. **PR-A — event substrate** (START HERE): add a `status` record kind to `index.jsonl`
   (`note_store.py` `_apply`/`_append` + `repository.py` in-memory map); add `status_of(note_id)` to
   the `NoteRepository` port + both impls; `planner.build_plan` uses `repo.status_of(n)` not
   `note.status`; `vault._frontmatter` writes the derived status. Tests: status event overrides
   creation status; done unblocks/leaves Now; rehydrates from disk.
2. **PR-B** capture-driven status updates (match note → propose → approve → append `status`).
3. **PR-C** `edit` events + per-note history + "what moved" digest in `Plan.md`.
4. **PR-D** resource references (frontmatter `resources:`/`links:`, render Obsidian links/embeds/placeholders; organizer extracts URLs/paths).
5. **PR-E** `grandplan attach <path|url>` + capture-driven artifact attach (parse vault → match → attach → mark progress → propagate to related notes).
6. **PR-F** voice capture (offline STT) behind the `Capturer` port.

### Invariants to honor (don't regress)
- **Lossless/append-only**: never mutate a stored note/original; updates are *events*, current state is *derived* (ADR-0007/0008).
- Keep the gate green (`ruff format --check`, `ruff check`, `mypy src`, `bandit -r src`, `pytest --cov`); branch off `main` (don't commit to main); one PR per slice; independent code review before merge.
- Optional deps stay lazily imported; tests hermetic (CI has no `[gui,llm,embeddings]` extras).
