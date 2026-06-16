# 1. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-06-15

## Context

grandplan has several load-bearing, hard-to-change decisions (CS130 L4). We want an
organizational memory of *why* choices were made, so they can be revisited rationally.

## Decision

We record architecturally significant decisions as short Markdown ADRs in `docs/adr/`,
numbered sequentially. Each ADR states Context, Decision, and Consequences. Lightweight
MADR-style; one decision per file; immutable once accepted (superseded by a new ADR, never edited).

## Consequences

- Decisions and their rationale are discoverable and reviewable.
- Superseding a decision means adding a new ADR that references the old one.
