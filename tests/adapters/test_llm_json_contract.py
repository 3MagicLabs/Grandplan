"""Cross-adapter LLM JSON robustness contract (#2).

The incident this pins: under load a long capture filled the model's context window, the
grammar-constrained JSON reply was TRUNCATED mid-object, bare `json.loads` failed, and the whole
organize silently fell back. The shared plumbing (`_ollama.loads_lenient` + `num_ctx`) fixed it —
this suite locks the guarantee in for EVERY adapter's parse entry point, so a new adapter (or a
refactor away from `loads_lenient`) that regresses the recovery behavior fails here immediately.

Matrix: every parser × {plain, code-fenced, prose-wrapped, truncated-mid-trailing-member}.
Payloads put their ESSENTIAL keys first and end with a sacrificial `zzz_extra` member, so the
truncation cut lands inside the sacrificial member and recovery must preserve the essentials.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable

import pytest

from grandplan.adapters._ollama import loads_lenient
from grandplan.adapters.kb_ask import parse_answer
from grandplan.adapters.kb_chat import parse_improvement, parse_plan
from grandplan.adapters.llm_contextual_reconciler import parse_relationships
from grandplan.adapters.llm_edit_detector import parse_edit
from grandplan.adapters.llm_entity_extractor import parse_entities
from grandplan.adapters.llm_placer import parse_placement
from grandplan.adapters.llm_reconciler import parse_relationship
from grandplan.adapters.llm_update_detector import parse_update
from grandplan.adapters.ollama_organizer import parse_proposed
from grandplan.core.models import NoteStatus, NoteType, Original, Source
from grandplan.core.reconcile import Relationship

_ORIGINAL = Original.capture("original text", Source(app="test"), "2026-07-03T00:00:00Z")

# (name, payload-with-essentials-first, parse, check) — one row per adapter parse entry point.
_ADAPTERS: list[tuple[str, dict[str, object], Callable[[str], object], Callable[[object], None]]]
_ADAPTERS = [
    (
        "organizer",
        {"title": "T", "type": "task", "tags": ["a"], "body": "Body text"},
        lambda raw: parse_proposed(raw, _ORIGINAL),
        lambda p: (  # type: ignore[func-returns-value]
            None,
            _assert(p.title == "T" and p.body == "Body text" and p.type is NoteType.TASK),
        )[0],
    ),
    (
        "placer",
        {"parent": "p1", "depends_on": [], "blocks": [], "waiting_on": []},
        lambda raw: parse_placement(raw, {"p1"}),
        lambda p: _assert(p.parent_id == "p1"),  # type: ignore[attr-defined]
    ),
    (
        "contextual-reconciler",
        {"relationships": [{"id": "a", "relationship": "builds_on"}]},
        lambda raw: parse_relationships(raw, {"a"}),
        lambda p: _assert(p == {"a": Relationship.BUILDS_ON}),
    ),
    (
        "pairwise-reconciler",
        {"relationship": "builds_on"},
        parse_relationship,
        lambda p: _assert(p is Relationship.BUILDS_ON),
    ),
    (
        "update-detector",
        {"update": "done"},
        parse_update,
        lambda p: _assert(p is NoteStatus.DONE),
    ),
    (
        "edit-detector",
        {"edit": {"title": "New title"}},
        parse_edit,
        lambda p: _assert(p is not None and p.title == "New title"),  # type: ignore[attr-defined]
    ),
    (
        "entity-extractor",
        {"entities": ["Ada Lovelace"]},
        parse_entities,
        lambda p: _assert(tuple(m.name for m in p) == ("Ada Lovelace",)),  # type: ignore[attr-defined]
    ),
    (
        "kb-ask",
        {"answer": "The answer.", "sources": ["a"]},
        lambda raw: parse_answer(raw, frozenset({"a"})),
        lambda p: _assert(p == ("The answer.", ("a",))),
    ),
    (
        "kb-plan",
        {"title": "P", "summary": "S.", "steps": ["one", "two", "three"], "sources": ["a"]},
        lambda raw: parse_plan(raw, frozenset({"a"})),
        lambda p: _assert(p["title"] == "P" and len(p["steps"]) == 3),  # type: ignore[index, arg-type]
    ),
    (
        "kb-improve",
        {"title": "Better title", "body": "Improved body.", "tags": ["a"], "rationale": "r"},
        parse_improvement,
        lambda p: _assert(p["body"] == "Improved body." and p["title"] == "Better title"),  # type: ignore[index]
    ),
]


def _assert(condition: bool) -> None:
    assert condition


def _payload(essentials: dict[str, object]) -> str:
    """Essentials first + a sacrificial trailing member (where the truncation cut will land)."""
    return json.dumps({**essentials, "zzz_extra": "x" * 40})


def _encodings(payload: str) -> dict[str, str]:
    cut = payload.index('"zzz_extra"') + 14  # mid-way through the sacrificial member
    return {
        "plain": payload,
        "fenced": f"```json\n{payload}\n```",
        "prose-wrapped": f"Sure! Here is the JSON you asked for:\n{payload}\nHope this helps.",
        "truncated": payload[:cut],  # context window ran out mid-reply
    }


@pytest.mark.parametrize(
    ("name", "essentials", "parse", "check"),
    _ADAPTERS,
    ids=lambda v: v if isinstance(v, str) else "",
)
@pytest.mark.parametrize("encoding", ["plain", "fenced", "prose-wrapped", "truncated"])
def test_every_adapter_recovers_a_usable_object_from_every_encoding(
    name: str,
    essentials: dict[str, object],
    parse: Callable[[str], object],
    check: Callable[[object], None],
    encoding: str,
) -> None:
    raw = _encodings(_payload(essentials))[encoding]
    check(parse(raw))  # must parse AND preserve the essential fields — no silent fallback


def test_property_valid_json_parses_identically_to_json_loads() -> None:
    # Poor-man's property test (no hypothesis dep): 300 seeded-random JSON values — nested
    # containers, quotes/escapes/unicode/newlines in strings, numbers, bools, nulls — must round-
    # trip through loads_lenient EXACTLY as json.loads would. Leniency may never change parsing.
    rng = random.Random(20260703)
    tricky = ['he said "hi"', "back\\slash", "line\nbreak", "emoji ✨", "ключ", "{brace}", ""]

    def value(depth: int) -> object:
        kind = rng.randrange(7 if depth < 3 else 5)
        if kind == 0:
            return rng.choice(tricky)
        if kind == 1:
            return rng.randint(-(10**9), 10**9)
        if kind == 2:
            return rng.random()
        if kind == 3:
            return rng.choice([True, False])
        if kind == 4:
            return None
        if kind == 5:
            return [value(depth + 1) for _ in range(rng.randrange(4))]
        return {rng.choice(tricky) + str(i): value(depth + 1) for i in range(rng.randrange(4))}

    for _ in range(300):
        document = json.dumps({"root": value(0)})
        assert loads_lenient(document) == json.loads(document)


# -- configurable num_ctx (#2): one env knob for every adapter ------------------------------------


def test_default_num_ctx_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from grandplan.adapters._ollama import DEFAULT_NUM_CTX, default_num_ctx

    monkeypatch.delenv("GRANDPLAN_NUM_CTX", raising=False)
    assert default_num_ctx() == DEFAULT_NUM_CTX
    monkeypatch.setenv("GRANDPLAN_NUM_CTX", "2048")
    assert default_num_ctx() == 2048  # read per call — no restart/import dance needed


@pytest.mark.parametrize("bad", ["banana", "-1", "0", "8.5"])
def test_default_num_ctx_ignores_malformed_values(
    bad: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from grandplan.adapters._ollama import DEFAULT_NUM_CTX, default_num_ctx

    monkeypatch.setenv("GRANDPLAN_NUM_CTX", bad)
    assert default_num_ctx() == DEFAULT_NUM_CTX  # logged + ignored, never a capture-time crash


def test_default_keep_alive_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # A loaded model's llama-server spins the CPU while idle, so keep-alive controls how long the
    # machine stays busy after the app is closed. Default 5m (down from 30m); GRANDPLAN_KEEP_ALIVE
    # tunes it (e.g. "0" unloads immediately for the lowest idle CPU).
    from grandplan.adapters._ollama import DEFAULT_KEEP_ALIVE, default_keep_alive

    monkeypatch.delenv("GRANDPLAN_KEEP_ALIVE", raising=False)
    assert default_keep_alive() == DEFAULT_KEEP_ALIVE == "5m"
    monkeypatch.setenv("GRANDPLAN_KEEP_ALIVE", "0")
    assert default_keep_alive() == "0"  # read per call — unloads right after each capture
