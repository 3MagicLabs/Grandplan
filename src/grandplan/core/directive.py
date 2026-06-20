"""Directives — an inbound "content + instruction" intake an AI agent fulfils (ROADMAP theme J).

The vision: from anywhere (eventually your phone), send a piece of content — a social post, a name, a
link — together with an instruction ("profile this person and their company, add what they're working
on to my notes, find a connection to my goals, and get started"). grandplan stores that as an
append-only **Directive** and an agent (over MCP) pulls the pending directives, fulfils each using the
existing append-only write tools (propose_note / extract_entities / place / set_status / search), and
marks it done.

This module is the **offline, in-house spine**: the Directive model, a registry of reusable
**Playbooks** (named preset instructions so you don't retype them), an append-only store, and the MCP
tool registry/dispatch. The networked pieces it enables — a phone→agent transport and live web
research — are separate, opt-in, off-by-default connectors (they don't live here), so the core stays
offline-by-default (QAS-1) and this whole module is pure + gated.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from grandplan.core.query import ToolSpec, _require_str, _schema


@dataclass(frozen=True)
class Playbook:
    """A named, reusable instruction the agent can run against captured content."""

    name: str
    description: str
    prompt: str


# Built-in playbooks. `profile-and-connect` is the user's headline scenario, decomposed into steps an
# agent fulfils with the existing read/write tools (entity extraction, semantic search, note/edge
# creation) — no new agent capability needed, just a preset instruction.
PLAYBOOKS: dict[str, Playbook] = {
    "profile-and-connect": Playbook(
        name="profile-and-connect",
        description="Profile the person/company in the content and connect it to my goals.",
        prompt=(
            "From the content: 1) identify the person and their company and current projects; "
            "2) create a note capturing what they're working on, and extract the people/orgs as "
            "entities (extract_entities); 3) search my existing goals/projects for a connection "
            "(search_notes) and, if you find one, place an edge to it; 4) if there's a concrete next "
            "step I could take, propose a task (propose_note) to get started. Keep everything "
            "append-only; never overwrite my notes."
        ),
    ),
    "capture-and-file": Playbook(
        name="capture-and-file",
        description="Summarize the content into a note and file it under the right goal/project.",
        prompt=(
            "Summarize the content into a single clear note (propose_note), tag it, and place it "
            "under the most relevant existing goal/project you can find (search_notes, then place)."
        ),
    ),
    "extract-actions": Playbook(
        name="extract-actions",
        description="Pull any action items out of the content as tasks.",
        prompt=(
            "Identify any concrete action items in the content and create a task note for each "
            "(propose_note, type=task), with a due date if one is implied."
        ),
    ),
}


@dataclass(frozen=True)
class Directive:
    """An append-only intake: captured content + the instruction to run on it.

    `id` is content-addressed over (content, instruction, created), so re-sending the same request
    collapses to one directive. `playbook` records which preset produced the instruction (or "" for an
    ad-hoc prompt). `done` is the derived completion state (set when a `done` record is appended).
    """

    id: str
    content: str
    instruction: str
    created: str
    playbook: str = ""
    done: bool = False

    @staticmethod
    def create(content: str, instruction: str, created: str, *, playbook: str = "") -> Directive:
        parts = (content, instruction, created)
        digest = hashlib.sha256(b"\x00".join(p.encode("utf-8") for p in parts)).hexdigest()
        return Directive(
            id=digest[:16],
            content=content,
            instruction=instruction,
            created=created,
            playbook=playbook,
        )


def resolve_instruction(*, playbook: str = "", prompt: str = "") -> tuple[str, str]:
    """Resolve (playbook name, ad-hoc prompt) into a (instruction, playbook-name) pair.

    A prompt overrides; otherwise the named playbook's prompt is used. Raises if neither is usable.
    """
    if prompt:
        return prompt, playbook
    if playbook:
        known = PLAYBOOKS.get(playbook)
        if known is None:
            allowed = ", ".join(sorted(PLAYBOOKS))
            raise ValueError(f"unknown playbook: {playbook!r} (known: {allowed})")
        return known.prompt, playbook
    raise ValueError("a directive needs a --prompt or a --playbook")


class DirectiveStore(Protocol):
    """Append-only store of directives with a derived done-state."""

    def add(self, directive: Directive) -> None: ...

    def pending(self) -> tuple[Directive, ...]: ...

    def all(self) -> tuple[Directive, ...]: ...

    def mark_done(self, directive_id: str) -> bool: ...

    def get(self, directive_id: str) -> Directive | None: ...


class InMemoryDirectiveStore:
    """In-memory DirectiveStore (the gated reference implementation)."""

    def __init__(self) -> None:
        self._items: dict[str, Directive] = {}

    def add(self, directive: Directive) -> None:
        self._items.setdefault(directive.id, directive)  # append-only + idempotent

    def all(self) -> tuple[Directive, ...]:
        return tuple(self._items.values())

    def pending(self) -> tuple[Directive, ...]:
        return tuple(d for d in self._items.values() if not d.done)

    def get(self, directive_id: str) -> Directive | None:
        return self._items.get(directive_id)

    def mark_done(self, directive_id: str) -> bool:
        existing = self._items.get(directive_id)
        if existing is None or existing.done:
            return False  # unknown or already done → idempotent no-op
        self._items[directive_id] = replace(existing, done=True)
        return True


class JsonlDirectiveStore:
    """Append-only JSON-Lines DirectiveStore: one `directive` record per intake, one `done` record
    per completion. State (incl. `done`) is *derived* by replaying the log — never mutated in place."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._items: dict[str, Directive] = {}
        # Guards the file append + the in-memory dict so concurrent writers stay consistent — the HTTP
        # intake server handles requests in threads, and `grandplan up` also writes from a watch thread.
        self._lock = threading.Lock()
        if path.exists():
            self._load()

    def _load(self) -> None:
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                record = line.rstrip("\n")
                if record:
                    self._apply(json.loads(record))

    def _apply(self, data: dict[str, object]) -> None:
        if data.get("kind") == "done":
            did = str(data["id"])
            if did in self._items:
                self._items[did] = replace(self._items[did], done=True)
            return
        directive = Directive(
            id=str(data["id"]),
            content=str(data["content"]),
            instruction=str(data["instruction"]),
            created=str(data["created"]),
            playbook=str(data.get("playbook", "")),
        )
        self._items.setdefault(directive.id, directive)

    def _append(self, record: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def add(self, directive: Directive) -> None:
        with self._lock:
            if directive.id in self._items:
                return  # append-only + idempotent on identical content
            self._append(
                {
                    "kind": "directive",
                    "id": directive.id,
                    "content": directive.content,
                    "instruction": directive.instruction,
                    "created": directive.created,
                    "playbook": directive.playbook,
                }
            )
            self._items[directive.id] = directive

    def all(self) -> tuple[Directive, ...]:
        return tuple(self._items.values())

    def pending(self) -> tuple[Directive, ...]:
        return tuple(d for d in self._items.values() if not d.done)

    def get(self, directive_id: str) -> Directive | None:
        return self._items.get(directive_id)

    def mark_done(self, directive_id: str) -> bool:
        with self._lock:
            existing = self._items.get(directive_id)
            if existing is None or existing.done:
                return False
            self._append({"kind": "done", "id": directive_id})
            self._items[directive_id] = replace(existing, done=True)
        return True


# --- MCP tool registry + dispatch (so an agent can pull + complete directives) --------------------

DIRECTIVE_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "list_directives",
        "List pending directives (content + instruction the agent should fulfil).",
        _schema({}, []),
    ),
    ToolSpec(
        "complete_directive",
        "Mark a directive done once you've fulfilled its instruction.",
        _schema({"directive_id": {"type": "string"}}, ["directive_id"]),
    ),
)


def directive_brief(directive: Directive) -> dict[str, object]:
    return {
        "id": directive.id,
        "content": directive.content,
        "instruction": directive.instruction,
        "playbook": directive.playbook,
        "created": directive.created,
        "done": directive.done,
    }


def dispatch_directive(store: DirectiveStore, name: str, arguments: dict[str, object]) -> object:
    """Route an MCP directive tool call to the store (validates name + required args)."""
    if name == "list_directives":
        return [directive_brief(d) for d in store.pending()]
    if name == "complete_directive":
        directive_id = _require_str(arguments, "directive_id")
        return {"ok": True, "applied": store.mark_done(directive_id), "directive_id": directive_id}
    raise ValueError(f"unknown tool: {name!r}")
