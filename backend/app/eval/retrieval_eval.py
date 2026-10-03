"""Retrieval evaluation: precision@k, recall@k, MRR and latency.

Runs the same benchmark questions through four retrieval configurations so the
ablation table in the report is generated, not hand-written.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from ..core.settings import settings
from .benchmark import BenchmarkItem, load_benchmark

Mode = Literal["dense", "bm25", "hybrid", "hybrid_rerank"]

MODES: tuple[Mode, ...] = ("dense", "bm25", "hybrid", "hybrid_rerank")


@dataclass
class ModeMetrics:
    mode: str
    questions: int = 0
    # precision@k normalised by k (the standard information-retrieval definition)
    precision_at_1: float = 0.0
    precision_at_3: float = 0.0
    precision_at_5: float = 0.0
    # success@k: did any gold record appear in the top k (k-normalisation-free)
    success_at_1: float = 0.0
    success_at_3: float = 0.0
    success_at_5: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    hit_rate: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    missed: list[str] = field(default_factory=list)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * len(ordered) - 1))))
    return ordered[index]


def _evaluate_mode(
    index, items: list[BenchmarkItem], mode: Mode, top_k: int = 5
) -> ModeMetrics:
    """Score one retrieval configuration against gold source ids."""
    metrics = ModeMetrics(mode=mode)
    latencies: list[float] = []

    p1: list[float] = []
    p3: list[float] = []
    p5: list[float] = []
    s1: list[float] = []
    s3: list[float] = []
    s5: list[float] = []
    recalls: list[float] = []
    reciprocal: list[float] = []
    hits: list[float] = []

    for item in items:
        # Unanswerable questions have no gold sources, so they cannot contribute
        # to retrieval precision; scoring them would reward finding nothing.
        if not item.gold_sources:
            continue

        started = time.perf_counter()
        results = index.retrieve(
            item.question, top_k=top_k, user_id=None, role="staff", mode=mode
        )
        latencies.append((time.perf_counter() - started) * 1000)

        retrieved_ids = [r.record_id for r in results]
        gold = set(item.gold_sources)

        def hits_at(k: int) -> int:
            return sum(1 for rid in retrieved_ids[:k] if rid in gold)

        p1.append(1.0 if hits_at(1) else 0.0)
        p3.append(hits_at(3) / 3.0)
        p5.append(hits_at(5) / 5.0)
        s1.append(1.0 if hits_at(1) else 0.0)
        s3.append(1.0 if hits_at(3) else 0.0)
        s5.append(1.0 if hits_at(5) else 0.0)
        recalls.append(hits_at(top_k) / len(gold))
        hits.append(1.0 if hits_at(top_k) else 0.0)

        rank = next(
            (i for i, rid in enumerate(retrieved_ids, start=1) if rid in gold), None
        )
        reciprocal.append(1.0 / rank if rank else 0.0)
        if rank is None:
            metrics.missed.append(item.id)

    metrics.questions = len(p1)
    if metrics.questions:
        metrics.precision_at_1 = round(sum(p1) / len(p1), 4)
        metrics.precision_at_3 = round(sum(p3) / len(p3), 4)
        metrics.precision_at_5 = round(sum(p5) / len(p5), 4)
        metrics.success_at_1 = round(sum(s1) / len(s1), 4)
        metrics.success_at_3 = round(sum(s3) / len(s3), 4)
        metrics.success_at_5 = round(sum(s5) / len(s5), 4)
        metrics.recall_at_k = round(sum(recalls) / len(recalls), 4)
        metrics.mrr = round(sum(reciprocal) / len(reciprocal), 4)
        metrics.hit_rate = round(sum(hits) / len(hits), 4)
    metrics.latency_p50_ms = round(_percentile(latencies, 50), 2)
    metrics.latency_p95_ms = round(_percentile(latencies, 95), 2)
    return metrics


def evaluate_retrieval(
    index,
    items: list[BenchmarkItem] | None = None,
    modes: tuple[Mode, ...] = MODES,
    top_k: int = 5,
    write: bool = True,
) -> dict[str, ModeMetrics]:
    items = items if items is not None else load_benchmark()
    results: dict[str, ModeMetrics] = {}
    for mode in modes:
        results[mode] = _evaluate_mode(index, items, mode, top_k=top_k)

    if write:
        target = settings.docs_dir / "eval" / "retrieval_latest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        stats = index.stats()
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "index": stats,
            "top_k": top_k,
            # Recorded so the table is self-explanatory: with the deterministic
            # hash fallback the dense path is a weaker lexical signal than BM25
            # and hybrid matches bm25. With a real embedder it should not.
            "embedder": stats.get("embedder"),
            "caveat": (
                "Dense fusion is down-weighted to 0 when embedder == 'hash-fallback' "
                "because it measured worse than BM25 alone. Re-run with "
                "sentence-transformers installed to measure the real hybrid gain."
            ),
            "modes": {mode: asdict(metrics) for mode, metrics in results.items()},
        }
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return results


def format_table(results: dict[str, ModeMetrics]) -> str:
    """A fixed-width table for the terminal and the report.

    Reports both conventions: ``P@k`` is the standard IR precision normalised by
    k, while ``S@k`` is success@k (any gold record retrieved). With one gold
    source per question the two differ by a factor of k, so quoting only P@k
    would understate retrieval badly.
    """
    header = (
        f"{'mode':<16}{'S@1':>7}{'S@3':>7}{'S@5':>7}{'P@1':>7}{'P@3':>7}{'P@5':>7}"
        f"{'recall':>8}{'MRR':>7}{'p50 ms':>9}{'p95 ms':>9}"
    )
    lines = [header, "-" * len(header)]
    for mode in MODES:
        metrics = results.get(mode)
        if metrics is None:
            continue
        lines.append(
            f"{metrics.mode:<16}{metrics.success_at_1:>7.3f}{metrics.success_at_3:>7.3f}"
            f"{metrics.success_at_5:>7.3f}{metrics.precision_at_1:>7.3f}"
            f"{metrics.precision_at_3:>7.3f}{metrics.precision_at_5:>7.3f}"
            f"{metrics.recall_at_k:>8.3f}{metrics.mrr:>7.3f}"
            f"{metrics.latency_p50_ms:>9.1f}{metrics.latency_p95_ms:>9.1f}"
        )
    return "\n".join(lines)


def format_by_kind(items: list[BenchmarkItem], index, mode: Mode = "hybrid_rerank") -> str:
    """Per-question-kind breakdown, useful for spotting weak categories."""
    kinds: dict[str, list[BenchmarkItem]] = {}
    for item in items:
        kinds.setdefault(item.kind, []).append(item)
    lines = [f"{'kind':<16}{'n':>5}{'P@1':>8}{'MRR':>8}", "-" * 37]
    for kind in sorted(kinds):
        metrics = _evaluate_mode(index, kinds[kind], mode)
        lines.append(
            f"{kind:<16}{metrics.questions:>5}{metrics.precision_at_1:>8.3f}"
            f"{metrics.mrr:>8.3f}"
        )
    return "\n".join(lines)
