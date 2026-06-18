# SPEC — PR-D: resource references (schema + render)

> Implements PR-D of ADR-0008 ("git for ideas"). Builds on PR-A/B/C. Adds **resource references** —
> external links, files, images, and **placeholder** expectations — extracted from a capture and
> rendered natively in the note's Obsidian Markdown.

## Goal

A capture often mentions a real artifact: a website, a GitHub repo, a PDF/image, a local file — or an
artifact the user still needs to make ("a resume website"). PR-D:
1. Models a **`Resource`** (kind: `link` / `image` / `file` / `placeholder`).
2. The **organizer extracts** URLs / image links / file paths / placeholder expectations from the
   capture (deterministic `HeuristicOrganizer` + the LLM `OllamaOrganizer`).
3. Resources are a **creation-time field** on `ProposedNote` / `Note` (like `status`), carried through
   `commit` and serialized in the index — they never change the note's content-addressed `id`.
4. The vault **renders resources natively in Obsidian**: a `## Resources` section with
   `[label](url)` links, `![[image]]` / `![label](url)` embeds, `[[file]]` wikilinks, and a visible
   **placeholder** line; plus a frontmatter `resources:` list of the concrete refs.

## Scope boundary (deferred to PR-E)

PR-D is **schema + render + extraction for a new capture**. The `resource` **event** kind,
`resources_of(note_id)` derivation, and the **capture-driven attach-to-an-existing-note** flow
(`grandplan attach <path|url>` → match the fulfilled note → attach → mark progress) are **PR-E**.
Because PR-D stores resources as a creation-time field (mirroring `status`), PR-E layers resource
events on top exactly as PR-B/PR-A did for status. Note-to-note **links are already edges** (rendered
as wikilinks in `## Links`) — PR-D's "resources" are *external/expected* artifacts, not note links.

## Invariants (must not regress)

- **Lossless / append-only:** resources are derived from the verbatim capture; the `Original` is
  untouched; the note's `id` excludes resources (extracting a URL never changes identity).
- **Deterministic core / no hidden clock:** `HeuristicOrganizer` extraction is pure regex over the
  capture text. The LLM path is lazily imported and unit-tested with an injected fake client.
- **Backward compatible:** `resources` defaults to `()`; old index records (no `resources` key) and
  every existing `Note(...)` / `ProposedNote(...)` construction keep working unchanged.

## Contracts

### `core/resources.py` (new)
```python
class ResourceKind(str, Enum):
    LINK = "link"          # external URL                → [label](url)
    IMAGE = "image"        # image URL or path           → ![label](url) / ![[ref]]
    FILE = "file"          # local file path / vault name → [label](path) / [[ref]]
    PLACEHOLDER = "placeholder"  # an expected, not-yet-existing artifact

@dataclass(frozen=True)
class Resource:
    kind: ResourceKind
    ref: str            # the URL / path, or (placeholder) a short artifact description
    label: str = ""     # optional display label

def extract_resources(text: str) -> tuple[Resource, ...]:
    """URLs (image-by-extension → IMAGE else LINK), file paths (image-by-extension → IMAGE else
    FILE), and a single placeholder for a 'make/create/… a <artifact>' phrase. Deduped, order-stable;
    URL spans are masked before path extraction so a URL's slashes aren't re-read as a path."""
```
- URL regex `https?://…`; path regex requires a path prefix (`/`, `~/`, `./`, `../`, `C:\`) **and** a
  file extension (conservative — avoids matching prose). Placeholder requires a creation verb
  immediately followed by an optional article and an artifact noun (`doc|page|site|resume|deck|pdf|…`)
  — so "make a resume" matches but "make sure the page loads" does not.

### Models (`core/models.py`)
- `ProposedNote` and `Note` gain `resources: tuple[Resource, ...] = ()`.
- `Note.from_proposed` carries `resources=proposed.resources`. The `id` hash is **unchanged**
  (still `original_id, title, body, type`) — resources are not identity.

### Organizers
- `HeuristicOrganizer.organize`: `resources=extract_resources(original.text)`.
- `OllamaOrganizer`: the prompt asks for an optional `"resources"` array of `{kind, ref, label?}`;
  `parse_proposed` validates each against `ResourceKind` (skips invalid) and **falls back to
  `extract_resources(original.text)`** when the model omits the field — the deterministic baseline
  still finds obvious URLs/paths.

### Persistence (`core/note_store.py`)
- `_note_to_dict` / `_note_from_dict` serialize `resources` (`{kind, ref, label}` each); absent key →
  `()` (back-compatible with PR-A/B/C index files).

### Vault render (`core/vault.py`)
- A `## Resources` section (when the note has resources), one bullet per resource:
  `link` → `[label or ref](ref)`; `image` → `![label](ref)` for a URL else `![[ref]]`; `file` →
  `[[ref]]` for a bare name else `[label or ref](ref)`; `placeholder` → `⬜ ref _(placeholder — to be
  attached)_`.
- Frontmatter gains `resources: [<ref>, …]` for the concrete (non-placeholder) refs, when present.
- The re-render path (PR-C `write_notes`) already passes `current_note`, which carries resources, so
  note files show resources after any re-projection.

## Tests (write first — RED), by layer

1. **resources:** each extraction case (http link, image URL → IMAGE, `/path/doc.pdf` → FILE,
   `~/pics/a.png` → IMAGE, "make a resume website" → PLACEHOLDER, plain prose → `()`); a URL's
   slashes are not re-extracted as a path; dedup; "make sure …" is **not** a placeholder.
2. **models:** `from_proposed` carries resources and the `id` is unchanged by them.
3. **organize / ollama_organizer:** heuristic extracts from the capture; the LLM parses a `resources`
   array, skips an invalid kind, and falls back to heuristic extraction when the field is absent.
4. **note_store:** a note with resources round-trips and rehydrates; an old record without the key
   loads with `resources == ()`.
5. **vault:** each kind renders the right Obsidian syntax; frontmatter `resources:` lists concrete
   refs; a placeholder renders visibly; no `## Resources` section when there are none.
6. **e2e:** a capture containing a URL produces a note whose `.md` renders the link in `## Resources`.

## Out of scope (later PRs)

`resource` events + `resources_of` derivation + `grandplan attach` + capture-driven attach (PR-E);
voice (PR-F); fetching/validating that a URL or file actually resolves.
