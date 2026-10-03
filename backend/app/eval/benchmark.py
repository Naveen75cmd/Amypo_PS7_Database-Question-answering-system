"""Benchmark loading.

The benchmark is JSONL so AMYPO's provided harness can be adapted without
changing our loader: only the field mapping would change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..core.settings import settings


@dataclass
class BenchmarkItem:
    id: str
    question: str
    expected_answer: str
    gold_sources: list[str] = field(default_factory=list)
    kind: str = "factoid"
    answerable: bool = True
    notes: str | None = None

    @property
    def is_unanswerable(self) -> bool:
        return not self.answerable


def benchmark_path() -> Path:
    return settings.eval_dir / "benchmark.jsonl"


def load_benchmark(path: Path | None = None) -> list[BenchmarkItem]:
    target = path or benchmark_path()
    if not target.exists():
        raise FileNotFoundError(
            f"benchmark not found at {target}. Run: python scripts/generate_data.py"
        )
    items: list[BenchmarkItem] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        raw = json.loads(line)
        items.append(
            BenchmarkItem(
                id=raw.get("id", f"q{len(items) + 1:03d}"),
                question=raw["question"],
                expected_answer=raw.get("expected_answer", ""),
                gold_sources=list(raw.get("gold_sources") or []),
                kind=raw.get("kind", "factoid"),
                answerable=bool(raw.get("answerable", True)),
                notes=raw.get("notes"),
            )
        )
    return items


def load_query_history() -> list[str]:
    """The 200 historical queries, used for cache pre-warming."""
    path = settings.eval_dir / "query_history.jsonl"
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line)["question"])
    return out
