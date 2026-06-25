# grandplan

A **Windows-first, fully-offline "second brain."** Select text in any app → capture it with a global
hotkey → a **local LLM** organizes it into a clean, atomic note (your original preserved **verbatim**)
→ you approve → it's filed as a linked, de-duplicated Markdown note in your **Obsidian vault**, and
projected into an actionable plan.

> Nothing leaves your machine.

## Pages
- **[[Getting-Started]]** — install, run the offline core, Windows setup.
- **[[Architecture]]** — ports & adapters, the capture pipeline, ADRs.
- **[[Security]]** — the local-trust model and how to report issues.

## Source of truth
The **repository** is canonical — see `README.md`, `SPEC.md`, `RESEARCH.md`, `docs/adr/`, and
`docs/research/`. This wiki is a friendly entry point, not a second source of truth.

## Constraints (non-negotiable)
- **Offline only** — zero network egress.
- **Lossless** — every captured original is preserved byte-for-byte; never mutated.
- **Modest hardware** — runs on a 16 GB-RAM machine, no GPU.
