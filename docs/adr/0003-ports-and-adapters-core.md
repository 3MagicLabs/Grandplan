# 3. Ports-and-adapters core; Windows target; dev-in-WSL / run-on-Windows split

- **Status:** Accepted
- **Date:** 2026-06-15

## Context

The app must run **natively on Windows** and capture selections from **any app**, fully **offline**.
But the highest-risk logic (losslessness, organization, linking, dedup) is platform-agnostic, and we
develop/gate under WSL2 (Linux), where Windows GUI/capture/LLM-runtime can't run.

## Decision

Adopt **ports & adapters (hexagonal)**. A platform-agnostic **core** depends only on ports —
`Capturer`, `Organizer`, `Embedder`, `Repository`, `VaultWriter`, `Planner` — and is fully
unit-testable with fakes, **gated in WSL2**. Thin **Windows adapters** implement the ports
(global-hotkey + clipboard/UIA capture; Ollama/llama.cpp organizer; sentence-transformer embedder;
SQLite+sqlite-vec repository; filesystem Obsidian VaultWriter) and are **integration-tested on Windows**.

## Consequences

- The risky core is covered by the gate regardless of platform; adapters stay thin.
- Swapping the LLM runtime or vector store is a localized adapter change (QAS-5: ≤1 day, no core change).
- The plan is a pure-core projection (`Planner` topologically sorts the dependency DAG).
