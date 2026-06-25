"""Eval: retrieval / reconcile quality vs the threshold knobs (issue #25), fully offline.

Builds a small LABELED set of notes — paraphrase clusters that *should* link, plus unrelated notes
that should *not* — runs the similarity scoring the reconciler uses, and reports duplicate/link
precision / recall / F1 at the shipped thresholds, plus a link-threshold sweep. This is the "organize
quality" dimension; the latency/memory dimension lives in scripts/bench_reconcile.py (ADR-0011 ties
them together).

The embedder is the offline `HashingEmbedder` (bag-of-words) — the deterministic baseline. A real
sentence-transformer (the `[embeddings]` extra) is expected to lift recall on heavy paraphrases. The
LLM-*organize* quality dimension needs Ollama and is described as a harness in ADR-0011.

Run:  PYTHONPATH=src python scripts/eval_retrieval.py
"""

from __future__ import annotations

import itertools

from grandplan.core.embed import HashingEmbedder
from grandplan.core.reconcile import _DEFAULT_DUPLICATE_THRESHOLD
from grandplan.core.repository import _dot

# Labeled clusters: each inner list is one concept; members SHOULD relate, across concepts they SHOULD NOT.
_CLUSTERS: list[list[str]] = [
    [
        "build the resume website",
        "create my personal resume site",
        "work on the resume webpage today",
        "finish building my CV website",
    ],
    [
        "call the dentist to book a checkup",
        "schedule a dental appointment",
        "book a dentist visit next week",
        "make an appointment with the dentist",
    ],
    [
        "research neural networks for the project",
        "study machine learning models for work",
        "read about deep learning architectures",
        "learn how transformer models work",
    ],
    [
        "buy groceries milk eggs and bread",
        "get milk eggs bread from the store",
        "pick up groceries: bread, milk, eggs",
    ],
    [
        "plan the team offsite in March",
        "organize the quarterly team retreat",
        "arrange the company offsite event",
    ],
    [
        "fix the login bug in the auth module",
        "debug the authentication login error",
        "resolve the broken sign in flow",
    ],
]

_LINK_THRESHOLD = 0.30  # SimilarityReconciler default
_DUP_THRESHOLD = _DEFAULT_DUPLICATE_THRESHOLD  # 0.90


def _build() -> tuple[list[tuple[float, ...]], list[int]]:
    """Return (embeddings, concept-label-per-note) over the flattened labeled set."""
    embedder = HashingEmbedder()
    embeddings: list[tuple[float, ...]] = []
    labels: list[int] = []
    for concept, texts in enumerate(_CLUSTERS):
        for text in texts:
            embeddings.append(embedder.embed(text))
            labels.append(concept)
    return embeddings, labels


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def _score_pairs(
    embeddings: list[tuple[float, ...]], labels: list[int]
) -> list[tuple[float, bool]]:
    """All unordered note pairs as (similarity, same_concept)."""
    pairs: list[tuple[float, bool]] = []
    for i, j in itertools.combinations(range(len(embeddings)), 2):
        pairs.append((_dot(embeddings[i], embeddings[j]), labels[i] == labels[j]))
    return pairs


def _evaluate(pairs: list[tuple[float, bool]], threshold: float) -> tuple[float, float, float]:
    tp = sum(1 for score, same in pairs if score >= threshold and same)
    fp = sum(1 for score, same in pairs if score >= threshold and not same)
    fn = sum(1 for score, same in pairs if score < threshold and same)
    return _prf(tp, fp, fn)


def main() -> None:
    embeddings, labels = _build()
    pairs = _score_pairs(embeddings, labels)
    positives = sum(1 for _, same in pairs if same)
    print(
        f"labeled set: {len(embeddings)} notes, {len(pairs)} pairs, {positives} same-concept pairs"
    )
    print("embedder: HashingEmbedder (offline bag-of-words, 256-dim)\n")

    print("at the shipped thresholds:")
    for name, t in (("link", _LINK_THRESHOLD), ("duplicate", _DUP_THRESHOLD)):
        p, r, f1 = _evaluate(pairs, t)
        print(f"  {name:>9} (>= {t:.2f}): precision {p:.2f}  recall {r:.2f}  F1 {f1:.2f}")

    print("\nlink-threshold sweep (precision/recall trade-off):")
    print(f"  {'thresh':>7} {'precision':>10} {'recall':>8} {'F1':>6}")
    for t in (0.10, 0.20, 0.30, 0.40, 0.50, 0.60):
        p, r, f1 = _evaluate(pairs, t)
        print(f"  {t:>7.2f} {p:>10.2f} {r:>8.2f} {f1:>6.2f}")
    print(
        "\nThe offline bag-of-words embedder favours precision over recall on heavy paraphrases "
        "(shared words drive similarity); a sentence-transformer is expected to raise recall."
    )


if __name__ == "__main__":
    main()
