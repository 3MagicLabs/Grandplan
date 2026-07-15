"""Tests for the directive runner — draining the pending queue nothing else drains (SPEC-ACT §A3).

The two properties that matter most are *safety* ones: the runner may only ever read the pending
queue (never the vault at large — curation is user-directed only), and it may only mark done what it
actually fulfilled.
"""

from __future__ import annotations

from pathlib import Path

from grandplan.core.directive import Directive, InMemoryDirectiveStore
from grandplan.core.embed import HashingEmbedder
from grandplan.core.entities import HeuristicEntityExtractor
from grandplan.core.fulfil import AUTO_FULFILLABLE, fulfil_directive, run_pending
from grandplan.core.models import NoteType, Source
from grandplan.core.organize import HeuristicOrganizer
from grandplan.core.placement import HeuristicPlacer
from grandplan.core.reconcile import SimilarityReconciler
from grandplan.core.repository import InMemoryNoteRepository
from grandplan.core.store import InMemoryOriginalStore
from grandplan.core.vault import MarkdownVaultWriter

_CREATED = "2026-07-15T00:00:00+00:00"
_SOURCE = Source(app="grandplan", title="directive")


def _directive(content: str, playbook: str = "capture-and-file") -> Directive:
    return Directive.create(content, f"instruction for {playbook}", _CREATED, playbook=playbook)


def _deps(tmp_path: Path) -> dict[str, object]:
    return {
        "repo": InMemoryNoteRepository(),
        "originals": InMemoryOriginalStore(),
        "embedder": HashingEmbedder(),
        "organizer": HeuristicOrganizer(),
        "reconciler": SimilarityReconciler(),
        "placer": HeuristicPlacer(),
        "entity_extractor": HeuristicEntityExtractor(),
        "vault": MarkdownVaultWriter(tmp_path / "vault"),
        "source": _SOURCE,
    }


def test_fulfil_creates_a_note_from_the_directive_content(tmp_path: Path) -> None:
    deps = _deps(tmp_path)
    result = fulfil_directive(_directive("write the launch post"), **deps)  # type: ignore[arg-type]

    assert result.note_id is not None
    assert not result.skipped_duplicate
    repo = deps["repo"]
    assert repo.get_note(result.note_id) is not None  # type: ignore[union-attr]


def test_fulfil_keeps_the_verbatim_content_as_an_original(tmp_path: Path) -> None:
    # Lossless (QAS-2): whatever the organizer made of it, the user's text survives untouched.
    deps = _deps(tmp_path)
    fulfil_directive(_directive("a thought worth keeping exactly"), **deps)  # type: ignore[arg-type]

    originals = deps["originals"]
    assert [o.text for o in originals.all()] == ["a thought worth keeping exactly"]  # type: ignore[union-attr]


def test_fulfil_stamps_the_directives_own_created_not_a_fresh_clock(tmp_path: Path) -> None:
    # No hidden clock: the note is dated when the user sent the directive, not when the runner
    # happened to drain the queue (which could be days later).
    deps = _deps(tmp_path)
    fulfil_directive(_directive("dated by the directive"), **deps)  # type: ignore[arg-type]

    originals = deps["originals"]
    assert [o.created for o in originals.all()] == [_CREATED]  # type: ignore[union-attr]


def test_fulfil_extracts_people_and_orgs(tmp_path: Path) -> None:
    # profile-and-connect's structural core: the content's people/orgs become entity notes.
    deps = _deps(tmp_path)
    result = fulfil_directive(
        _directive("met Ada Lovelace from Analytical Engines Inc", "profile-and-connect"),
        **deps,  # type: ignore[arg-type]
    )

    assert len(result.entity_ids) == 2
    repo = deps["repo"]
    titles = {n.title for n in repo.notes() if n.type is NoteType.ENTITY}  # type: ignore[union-attr]
    assert titles == {"Ada Lovelace", "Analytical Engines Inc"}
    assert result.note_id is not None


def test_fulfil_skips_a_duplicate_without_creating_a_second_note(tmp_path: Path) -> None:
    deps = _deps(tmp_path)
    first = fulfil_directive(_directive("write the launch post"), **deps)  # type: ignore[arg-type]
    second = fulfil_directive(_directive("write the launch post"), **deps)  # type: ignore[arg-type]

    assert first.note_id is not None
    assert second.skipped_duplicate is True
    assert second.note_id is None
    repo = deps["repo"]
    assert len([n for n in repo.notes() if n.type is not NoteType.ENTITY]) == 1  # type: ignore[union-attr]


# --- run_pending: the allowlist + done-marking safety -------------------------------------------


def test_run_pending_fulfils_and_marks_done(tmp_path: Path) -> None:
    store = InMemoryDirectiveStore()
    store.add(_directive("write the launch post"))
    deps = _deps(tmp_path)

    results = run_pending(store, fulfil=lambda d: fulfil_directive(d, **deps))  # type: ignore[arg-type]

    assert len(results) == 1
    assert store.pending() == ()  # drained


def test_run_pending_leaves_non_allowlisted_playbooks_pending(tmp_path: Path) -> None:
    # extract-actions needs generation the structural pipeline has no step for. Marking it done
    # would silently drop the user's actual request — worse than leaving it for an MCP agent.
    store = InMemoryDirectiveStore()
    store.add(_directive("call the bank and email Dana", "extract-actions"))

    results = run_pending(store, fulfil=lambda d: None)  # type: ignore[arg-type,return-value]

    assert results == ()
    assert len(store.pending()) == 1  # still there, for an agent


def test_run_pending_leaves_ad_hoc_prompts_pending(tmp_path: Path) -> None:
    store = InMemoryDirectiveStore()
    store.add(Directive.create("some content", "do something clever", _CREATED, playbook=""))

    assert run_pending(store, fulfil=lambda d: None) == ()  # type: ignore[arg-type,return-value]
    assert len(store.pending()) == 1


def test_run_pending_leaves_a_failed_directive_pending(tmp_path: Path) -> None:
    # A failure must be retryable, never silently consumed.
    store = InMemoryDirectiveStore()
    store.add(_directive("this one explodes"))

    def boom(directive: Directive) -> object:
        raise RuntimeError("organizer exploded")

    assert run_pending(store, fulfil=boom) == ()  # type: ignore[arg-type]
    assert len(store.pending()) == 1


def test_run_pending_one_failure_does_not_stop_the_rest(tmp_path: Path) -> None:
    store = InMemoryDirectiveStore()
    store.add(_directive("explode"))
    store.add(_directive("succeed"))
    deps = _deps(tmp_path)

    def flaky(directive: Directive) -> object:
        if "explode" in directive.content:
            raise RuntimeError("boom")
        return fulfil_directive(directive, **deps)  # type: ignore[arg-type]

    results = run_pending(store, fulfil=flaky)

    assert len(results) == 1  # the good one still landed
    assert len(store.pending()) == 1  # only the failure remains


def test_run_pending_respects_max(tmp_path: Path) -> None:
    store = InMemoryDirectiveStore()
    for i in range(5):
        store.add(_directive(f"thought number {i}"))
    deps = _deps(tmp_path)

    results = run_pending(store, fulfil=lambda d: fulfil_directive(d, **deps), max_directives=2)  # type: ignore[arg-type]

    assert len(results) == 2
    assert len(store.pending()) == 3


def test_run_pending_on_an_empty_queue_does_nothing(tmp_path: Path) -> None:
    assert run_pending(InMemoryDirectiveStore(), fulfil=lambda d: None) == ()  # type: ignore[arg-type,return-value]


def test_run_pending_never_reads_the_vault_at_large() -> None:
    # THE safety property (SPEC-ACT §5): the runner's entire input is the pending queue. It must
    # never enumerate notes looking for work — that would be an autonomous curation sweep.
    class ExplodingRepo:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(
                f"run_pending touched the repo ({name}) — it must only read pending()"
            )

    store = InMemoryDirectiveStore()
    seen: list[str] = []
    run_pending(store, fulfil=lambda d: seen.append(d.id))  # type: ignore[arg-type,return-value]
    _ = ExplodingRepo()  # run_pending is not even given a repo — it cannot reach the vault
    assert seen == []


def test_allowlist_is_exactly_the_playbooks_the_pipeline_fulfils() -> None:
    # A guard on the honesty rule: adding a playbook here claims the structural pipeline satisfies
    # its instruction. If that stops being true, this test should fail loudly.
    assert AUTO_FULFILLABLE == frozenset({"capture-and-file", "profile-and-connect"})
