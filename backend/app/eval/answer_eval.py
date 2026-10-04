"""End-to-end answer evaluation: does /ask answer, cite, and abstain correctly?

The retrieval harness scores *ranking*; this one scores the thing the user
actually receives. It runs every benchmark question through the real
``AskPipeline`` and reports, separately for answerable and unanswerable items:

* coverage — answerable questions that were answered (did not abstain);
* numeric agreement — answerable questions whose expected numbers all appear in
  the answer (a strict, cheap-to-compute correctness proxy);
* citation rate — answers that carry at least one source;
* abstention — unanswerable questions that correctly abstained;
* hallucination — unanswerable questions that were answered anyway.

It defaults to ``force_extractive=True`` so the numbers are reproducible without a
pulled model; pass ``force_extractive=False`` to measure the real generation
path. The threshold sweep that set ``settings.claim_similarity_threshold`` was
run with this harness.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .benchmark import BenchmarkItem, load_benchmark

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class AnswerMetrics:
    answerable: int = 0
    answered: int = 0
    answerable_abstained: int = 0
    # Answerable items whose expected numbers all appear in the answer.
    numeric_items: int = 0
    numeric_hits: int = 0
    cited: int = 0
    unanswerable: int = 0
    unanswerable_abstained: int = 0
    hallucinated: int = 0
    hallucinated_ids: list[str] = field(default_factory=list)
    missed_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["answer_coverage"] = round(self.answered / self.answerable, 4) if self.answerable else 0.0
        data["numeric_agreement"] = (
            round(self.numeric_hits / self.numeric_items, 4) if self.numeric_items else 0.0
        )
        data["citation_rate"] = round(self.cited / self.answered, 4) if self.answered else 0.0
        data["abstention_rate"] = (
            round(self.unanswerable_abstained / self.unanswerable, 4) if self.unanswerable else 0.0
        )
        return data


def evaluate_answers(
    pipeline,
    items: list[BenchmarkItem] | None = None,
    user_id: str | None = None,
    role: str = "staff",
    force_extractive: bool = True,
) -> AnswerMetrics:
    """Run the pipeline over the benchmark and collect the metrics above."""
    items = items or load_benchmark()
    metrics = AnswerMetrics()

    for item in items:
        result = pipeline.answer(
            item.question, user_id=user_id, role=role, force_extractive=force_extractive
        )
        if item.answerable:
            metrics.answerable += 1
            if result.abstained:
                metrics.answerable_abstained += 1
                metrics.missed_ids.append(item.id)
            else:
                metrics.answered += 1
                if result.sources:
                    metrics.cited += 1
                expected_numbers = set(_NUMBER_RE.findall(item.expected_answer))
                if expected_numbers:
                    metrics.numeric_items += 1
                    if expected_numbers <= set(_NUMBER_RE.findall(result.answer)):
                        metrics.numeric_hits += 1
        else:
            metrics.unanswerable += 1
            if result.abstained:
                metrics.unanswerable_abstained += 1
            else:
                metrics.hallucinated += 1
                metrics.hallucinated_ids.append(item.id)

    return metrics


def format_report(metrics: AnswerMetrics) -> str:
    """A compact table for the terminal and the docs."""
    lines = [
        "End-to-end answer evaluation",
        "=" * 52,
        f"answerable questions       {metrics.answerable}",
        f"  answered                  {metrics.answered}/{metrics.answerable}",
        f"  abstained                 {metrics.answerable_abstained}",
        f"  numeric agreement         {metrics.numeric_hits}/{metrics.numeric_items}",
        f"  answers with a citation   {metrics.cited}/{metrics.answered}",
        f"unanswerable questions      {metrics.unanswerable}",
        f"  correctly abstained       {metrics.unanswerable_abstained}/{metrics.unanswerable}",
        f"  answered anyway           {metrics.hallucinated}",
    ]
    if metrics.hallucinated_ids:
        lines.append(f"  not abstained: {', '.join(metrics.hallucinated_ids)}")
    return "\n".join(lines)


def _main() -> None:  # pragma: no cover - manual harness
    import argparse

    from ..api.ask_service import AskPipeline
    from ..core.container import get_container
    from ..db import get_connection

    parser = argparse.ArgumentParser(description="Evaluate /ask end to end on the benchmark")
    parser.add_argument("--user-id", default=None, help="ask as this student id")
    parser.add_argument("--role", default="staff", choices=["student", "staff"])
    parser.add_argument(
        "--model",
        action="store_true",
        help="use the real generation path instead of the extractive fallback",
    )
    args = parser.parse_args()

    get_connection()
    container = get_container()
    pipeline = AskPipeline(
        container.get("index"), container.get("llm"), container.get("verifier")
    )
    metrics = evaluate_answers(
        pipeline,
        user_id=args.user_id,
        role=args.role,
        force_extractive=not args.model,
    )
    print(format_report(metrics))


if __name__ == "__main__":  # pragma: no cover
    _main()
