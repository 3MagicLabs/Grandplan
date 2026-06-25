# Architecture

**Ports & adapters.** A platform-agnostic **core** (segment · preserve-verbatim · organize · embed ·
link · dedup · project) depends only on **ports** (`Capturer`, `Organizer`, `Embedder`,
`NoteRepository`, `VaultWriter`, `Planner`). Windows-only **adapters** (global-hotkey capture, local
LLM runtime, the Obsidian vault) implement those ports. The core is fully unit-tested and is the part
the quality gate governs.

## The capture pipeline
`capture → organize (local LLM) → embed → reconcile (dedup/link) → review (human) → commit
(append-only) → re-project (Plan.md / graph.json)`. Serialized through one worker (ADR-0006): one model
call at a time, single writer, fault-isolated, with progress + backpressure surfaced (ADR-0010).

## Data model
- The **Obsidian vault** (Markdown) is the source of truth.
- An internal **append-only event log** (`index.jsonl`, ADR-0008) records note / edge / status / edit /
  resource events; current state is *derived* ("git for ideas"). Originals are never mutated.

## Decisions (ADRs)
See `docs/adr/` — notably 0003 (ports & adapters), 0006 (capture serialization), 0007 (relationship
classification), 0008 (event-sourced progress), 0009 (scalability), 0010 (throughput), 0011 (quality
evaluation).

## Agent-operable vault
A local **MCP server** (`grandplan mcp -o <vault>`) exposes read/search/distill + append-only write
tools over stdio (offline). See `docs/specs/SPEC-AGENT-VAULT.md`; the future KB agent is sketched in
`docs/specs/SPEC-AGENT-KB.md`.
