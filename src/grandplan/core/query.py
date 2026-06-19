"""VaultQuery — a pure, offline read facade over the knowledge graph (agent-operable vault).

Exposes the vault to AI agents as plain JSON-serializable data: list/get/search notes, the plan, the
masterplan hierarchy, the JSON graph, and the health report. It is pure (no IO beyond the injected
repo/originals/embedder) and offline, so it is fully unit-tested without the optional `mcp` dep — the
MCP server (adapters/mcp_server.py) is a thin shell that registers `TOOLS` and routes `call-tool`
through `dispatch`. Read-only: nothing here mutates the vault (agent writes are a separate, append-only
step that reuses the PR-A…PR-G event operations).
"""

from __future__ import annotations

from dataclasses import dataclass

from grandplan.core.graph import to_graph
from grandplan.core.models import Note
from grandplan.core.planner import Plan, build_plan, build_timeline
from grandplan.core.ports import Embedder, NoteRepository
from grandplan.core.report import build_run_report
from grandplan.core.store import OriginalStore


@dataclass(frozen=True)
class VaultQuery:
    """Read operations over a vault's repo + originals + embedder, returning agent-friendly dicts."""

    repo: NoteRepository
    originals: OriginalStore
    embedder: Embedder

    def list_notes(self) -> list[dict[str, object]]:
        return [self._brief(note) for note in self.repo.current_notes()]

    def get_note(self, note_id: str) -> dict[str, object] | None:
        note = self.repo.current_note(note_id)
        if note is None:
            return None
        by_id = {n.id: n for n in self.repo.current_notes()}
        links = [
            {
                "kind": edge.kind.value,
                "target_id": edge.target_id,
                "target_title": by_id[edge.target_id].title if edge.target_id in by_id else None,
            }
            for edge in self.repo.edges()
            if edge.source_id == note_id
        ]
        original = self.originals.get(note.original_id)
        return {
            **self._brief(note),
            "body": note.body,
            "original": original.text if original is not None else None,
            "resources": [
                {"kind": r.kind.value, "ref": r.ref, "label": r.label}
                for r in self.repo.resources_of(note_id)
            ],
            "history": [event.summary() for event in self.repo.history_of(note_id)],
            "links": links,
        }

    def search_notes(self, query: str, limit: int = 5) -> list[dict[str, object]]:
        embedding = self.embedder.embed(query)
        return [
            {"id": note.id, "title": note.title, "type": note.type.value, "score": round(score, 4)}
            for note, score in self.repo.most_similar(embedding, limit=limit)
        ]

    def get_plan(self) -> dict[str, object]:
        plan = build_plan(self.repo)
        return {
            "now": [self._brief(note) for note in plan.now],
            "blocked": [
                {
                    "note": self._brief(item.note),
                    "blocked_by": [self._brief(blocker) for blocker in item.blocked_by],
                }
                for item in plan.blocked
            ],
            "needs_review": [self._brief(note) for note in plan.needs_review],
            "cycle": [self._brief(note) for note in plan.cycle],
        }

    def get_masterplan(self) -> dict[str, object]:
        plan = build_plan(self.repo)
        return {"roots": [self._tree(plan, root_id) for root_id in plan.root_ids]}

    def get_timeline(self) -> dict[str, object]:
        timeline = build_timeline(self.repo)
        return {
            "ready": [self._brief(note) for note in timeline.ready],
            "waiting": [
                {
                    "note": self._brief(item.note),
                    "blocked_by": [blocker.title for blocker in item.blocked_by],
                }
                for item in timeline.waiting
            ],
            "scheduled": [
                {"id": note.id, "title": note.title, "due": note.due} for note in timeline.scheduled
            ],
            "conflicts": list(timeline.conflicts),
        }

    def get_graph(self) -> dict[str, object]:
        return to_graph(self.repo)

    def doctor(self) -> dict[str, object]:
        report = build_run_report(self.repo, self.originals)
        return {
            "note_count": report.note_count,
            "type_counts": dict(report.type_counts),
            "horizon_counts": dict(report.horizon_counts),
            "edge_counts": dict(report.edge_counts),
            "structural_edges": report.structural_edges,
            "semantic_edges": report.semantic_edges,
            "isolated": list(report.isolated),
            "low_quality": [
                {"title": title, "issues": list(issues)} for title, issues in report.low_quality
            ],
        }

    def _brief(self, note: Note) -> dict[str, object]:
        return {
            "id": note.id,
            "title": note.title,
            "type": note.type.value,
            "status": note.status.value,
            "horizon": note.horizon.value,
            "tags": list(note.tags),
            "due": note.due,
        }

    def _tree(self, plan: Plan, note_id: str) -> dict[str, object]:
        note = plan.by_id[note_id]
        return {
            "id": note_id,
            "title": note.title,
            "type": note.type.value,
            "horizon": note.horizon.value,
            "children": [self._tree(plan, child) for child in plan.child_ids.get(note_id, ())],
        }


@dataclass(frozen=True)
class ToolSpec:
    """An MCP tool definition: name, human description, and a JSON-Schema for its arguments."""

    name: str
    description: str
    input_schema: dict[str, object]


def _schema(properties: dict[str, object], required: list[str]) -> dict[str, object]:
    return {"type": "object", "properties": properties, "required": required}


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "list_notes",
        "List all notes (id, title, type, status, horizon, tags, due).",
        _schema({}, []),
    ),
    ToolSpec(
        "get_note",
        "Get one note in full: fields + verbatim original + resources + history + outgoing links.",
        _schema({"note_id": {"type": "string", "description": "the note id"}}, ["note_id"]),
    ),
    ToolSpec(
        "search_notes",
        "Find notes semantically similar to a query string, ranked by similarity.",
        _schema(
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "description": "max results (default 5)"},
            },
            ["query"],
        ),
    ),
    ToolSpec(
        "get_plan",
        "The actionable plan: now / blocked / needs-review / dependency cycles.",
        _schema({}, []),
    ),
    ToolSpec(
        "get_masterplan",
        "The horizon-stratified hierarchy (goals → projects → actions).",
        _schema({}, []),
    ),
    ToolSpec(
        "get_timeline",
        "Feasible execution order: ready / waiting / scheduled-by-date / conflicts.",
        _schema({}, []),
    ),
    ToolSpec("get_graph", "The full JSON knowledge graph: nodes + typed edges.", _schema({}, [])),
    ToolSpec(
        "doctor",
        "A health report: counts, structural-vs-semantic edges, low-quality notes.",
        _schema({}, []),
    ),
)


def dispatch(query: VaultQuery, name: str, arguments: dict[str, object]) -> object:
    """Route an MCP tool call to the matching VaultQuery method (validates name + required args)."""
    if name == "list_notes":
        return query.list_notes()
    if name == "get_note":
        return query.get_note(_require_str(arguments, "note_id"))
    if name == "search_notes":
        raw_limit = arguments.get("limit", 5)
        limit = raw_limit if isinstance(raw_limit, int) and raw_limit > 0 else 5
        return query.search_notes(_require_str(arguments, "query"), limit=limit)
    if name == "get_plan":
        return query.get_plan()
    if name == "get_masterplan":
        return query.get_masterplan()
    if name == "get_timeline":
        return query.get_timeline()
    if name == "get_graph":
        return query.get_graph()
    if name == "doctor":
        return query.doctor()
    raise ValueError(f"unknown tool: {name!r}")


def _require_str(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing required string argument: {key!r}")
    return value
