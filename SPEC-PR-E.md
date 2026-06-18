# SPEC — PR-E: artifact-attach flow

> Implements PR-E of ADR-0008 ("git for ideas"). Builds on PR-D (resource schema/render). Adds the
> `resource` **event** kind and a `grandplan attach` command: "here's the doc for note X → update my
> vault."

## Goal

Given a real artifact (a file path or URL), find the existing note it fulfils by embedding similarity
and **attach it as a `resource` event** (append-only; the note is never mutated). The attachment
renders in the note's `## Resources` section and appears in its history + the `Plan.md` "what moved"
digest — so attaching is itself recorded progress.

## Contracts

- **`NoteEvent.kind`** gains `"resource"` (+ a `resource: Resource | None` field); `summary()` →
  `+<kind>: <ref>`. The index event kind `resource` is replayed and serialized like status/edit.
- **`NoteRepository`** gains:
  - `add_resource(note_id, resource, *, at=None)` — append a `resource` event. No-op if the note is
    unknown (orphan-guarded) or the resource is already present by `(kind, ref)` (idempotent).
  - `resources_of(note_id) -> tuple[Resource, ...]` — derived = creation-time resources (PR-D) +
    attached ones, deduped by `(kind, ref)`, order-stable.
  - `current_note` folds the derived resources onto the note, so the planner/graph/vault render them.
- **`core/resources.py`**: `classify_reference(ref, *, label="")` (URL→link/image, path→file/image)
  and `describe_reference(ref)` (last path/URL segment, sans extension, separators→spaces) for
  matching.
- **`core/attach.py`**: `attach(ref, *, repo, embedder, description=None, label="", match_threshold=0.30)`
  → `AttachResult(note, resource) | None`. Classifies the ref, embeds `description or
  describe_reference(ref)`, takes the single best match above threshold, and `add_resource`s it.
- **CLI**: `grandplan attach <ref> -o <vault> [--describe TEXT] [--embeddings]` — loads the persistent
  index (the GUI's, outside the synced vault), attaches, and re-projects (so the note `.md` re-renders
  with the resource + history). `--embeddings` must match the embedder the vault was built with.

## Invariants

- **Lossless/append-only**: attaching is an event; the stored note/original are never mutated.
- **Idempotent + orphan-guarded**; **no hidden clock** (the `at` timestamp is caller-supplied).
- **Safe**: `attach` only *records* the reference string — it never fetches/opens the URL or file.
- **Hermetic**: matching uses the offline `HashingEmbedder` by default.

## Deferred (later)

Capture-driven attach **in the review dialog** (the CLI command is the headline); propagation of an
attachment to related notes (single best match only for safety); auto status bump on attach (status
changes stay PR-B's explicit, human-approved flow); fetching/validating that the ref resolves.
