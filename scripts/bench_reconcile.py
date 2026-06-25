"""Benchmark: reconcile / similarity-search latency + index memory at vault scale (issue #4).

Fully offline and dependency-free — uses the deterministic `HashingEmbedder` and the in-memory
`NoteRepository`, so it measures the *algorithmic* cost of the brute-force similarity search that
`reconcile` performs on every capture (`repo.most_similar`). The goal is to decide whether an ANN /
on-disk vector index is warranted (see docs/adr/0009-scalability-index-and-reconcile.md).

Run:  PYTHONPATH=src python scripts/bench_reconcile.py
Offline; takes ~30-60s. Numbers are indicative (pure-Python, single core); the *shape* (per-query
O(N), cumulative O(N^2)) is what matters, not absolute ms on any one machine.
"""

from __future__ import annotations

import gc
import random
import statistics
import time
import tracemalloc

from grandplan.core.embed import HashingEmbedder
from grandplan.core.models import Note, NoteType
from grandplan.core.repository import InMemoryNoteRepository

_VOCAB = (
    "project meeting schedule plan research model data note idea task vault graph link dedup "
    "capture organize embed reconcile place obsidian markdown offline llm ollama gemma qwen "
    "index memory latency throughput backpressure pipeline worker queue review status edit "
    "entity person org resource attach calendar agenda urgency quality report render export"
).split()

_SIZES = (100, 1_000, 10_000)
_EMBEDDER = HashingEmbedder()  # 256-dim unit vectors


def _make_note(rng: random.Random, i: int) -> tuple[Note, tuple[float, ...]]:
    text = " ".join(rng.choices(_VOCAB, k=rng.randint(8, 20)))
    note = Note(id=f"n{i}", original_id=f"o{i}", title=text[:60], body=text, type=NoteType.IDEA)
    return note, _EMBEDDER.embed(text)


def _build(n: int, rng: random.Random) -> tuple[InMemoryNoteRepository, float, float]:
    """Build an n-note index; return (repo, build_seconds, index_MiB)."""
    gc.collect()
    tracemalloc.start()
    start = time.perf_counter()
    repo = InMemoryNoteRepository()
    for i in range(n):
        note, emb = _make_note(rng, i)
        repo.add_note(note, emb)
    build_s = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return repo, build_s, peak / (1024 * 1024)


def _query_latency_ms(
    repo: InMemoryNoteRepository, n: int, rng: random.Random
) -> tuple[float, float]:
    """p50 / p95 latency (ms) of a single `most_similar` search over an n-note index."""
    samples = max(20, min(200, 2_000_000 // n))  # fewer probes at large N to bound runtime
    times: list[float] = []
    for _ in range(samples):
        _, emb = _make_note(rng, rng.randint(0, n))
        start = time.perf_counter()
        repo.most_similar(emb, limit=5, threshold=0.30)
        times.append((time.perf_counter() - start) * 1000)
    times.sort()
    p50 = statistics.median(times)
    p95 = times[min(len(times) - 1, int(0.95 * len(times)))]
    return p50, p95


def main() -> None:
    rng = random.Random(1234)
    print(
        f"{'N':>8} {'build_s':>9} {'index_MiB':>10} {'query_p50_ms':>13} {'query_p95_ms':>13} "
        f"{'cum_reconcile_s (=N*p50)':>26}"
    )
    print("-" * 84)
    for n in _SIZES:
        repo, build_s, mib = _build(n, rng)
        p50, p95 = _query_latency_ms(repo, n, rng)
        cumulative = (
            n * p50 / 1000
        )  # building an N-note vault reconciles once per note => N queries
        print(f"{n:>8} {build_s:>9.3f} {mib:>10.2f} {p50:>13.4f} {p95:>13.4f} {cumulative:>26.2f}")
    print("-" * 84)
    print("Per-query cost grows ~O(N); cumulative reconcile to build an N-note vault is ~O(N^2).")


if __name__ == "__main__":
    main()
