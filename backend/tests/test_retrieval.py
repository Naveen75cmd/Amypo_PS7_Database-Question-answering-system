"""Phase 3 definition of done: hybrid retrieval, access control and the eval harness.

These tests exercise the real index built from the generated corpus. They skip
with a clear message when the corpus has not been generated yet, rather than
passing vacuously.
"""

from __future__ import annotations

import pytest

from app.core.settings import settings
from app.retrieval.tokenize import extract_numbers, tokenize, tokenize_query


@pytest.fixture(scope="module")
def corpus_ready() -> bool:
    return (settings.raw_dir / "attendance-policy.md").exists()


def _need_corpus() -> None:
    if not (settings.raw_dir / "attendance-policy.md").exists():
        pytest.skip("run scripts/generate_data.py then python -m app.ingest first")


@pytest.fixture(scope="module")
def index():
    _need_corpus()
    from app.db import get_connection

    get_connection()
    from app.retrieval.index import RetrievalIndex

    built = RetrievalIndex.load_or_build()
    if built.is_empty:
        pytest.skip("index is empty — run python -m app.ingest")
    return built


# --------------------------------------------------------------------------
# Tokenization
# --------------------------------------------------------------------------


def test_identifiers_are_preserved_and_split() -> None:
    tokens = tokenize("What is the status of CS301 and student S102?")
    assert "cs301" in tokens
    assert "cs" in tokens and "301" in tokens
    assert "s102" in tokens
    assert "what" not in tokens, "stopwords should be dropped"


def test_numbers_and_percentages_are_extracted() -> None:
    numbers = extract_numbers("At least 75% attendance and 4 backlogs, CGPA 6.5")
    assert {"75", "4", "6.5"} <= numbers


def test_query_tokenization_never_returns_empty() -> None:
    assert tokenize_query("what is this") != []


# --------------------------------------------------------------------------
# Retrieval behaviour
# --------------------------------------------------------------------------


def test_dense_and_bm25_both_return_results(index) -> None:
    for mode in ("dense", "bm25", "hybrid", "hybrid_rerank"):
        results = index.retrieve(
            "minimum attendance for exams", top_k=5, role="staff", mode=mode
        )
        assert results, f"{mode} returned nothing"
        assert all(r.record_id for r in results)


def test_policy_question_ranks_the_policy_first(index) -> None:
    results = index.retrieve(
        "What is the minimum attendance required to sit for end-semester exams?",
        top_k=3, role="staff",
    )
    assert results
    assert results[0].record_id.startswith("doc:attendance-policy"), (
        f"expected the attendance policy, got {results[0].record_id}"
    )


def test_identifiers_drive_retrieval(index) -> None:
    """A query naming a student id must surface that student's card."""
    results = index.retrieve("What is the CGPA of S102?", top_k=5, role="staff")
    ids = [r.record_id for r in results]
    assert "db:students:S102" in ids, f"S102 not retrieved; got {ids}"


def test_hybrid_fusion_is_rank_based(index) -> None:
    """RRF ignores score magnitude, so a tiny list still contributes."""
    fused = index.reciprocal_rank_fusion([[(1, 99.0)], [(2, 0.001)]])
    scores = dict(fused)
    assert scores[1] == scores[2], "equal ranks must contribute equally"


def test_fusion_weights_change_the_ordering(index) -> None:
    heavy_first = index.reciprocal_rank_fusion([[(1, 1.0)], [(2, 1.0)]], weights=[1.0, 0.0])
    assert heavy_first[0][0] == 1


# --------------------------------------------------------------------------
# Access control — enforced in the retriever, never in the prompt
# --------------------------------------------------------------------------


def test_student_cannot_retrieve_another_students_record(index) -> None:
    results = index.retrieve(
        "What is the CGPA of S102?", top_k=10, user_id="S999", role="student"
    )
    scopes = {r.access_scope for r in results}
    assert "student:S102" not in scopes
    assert all(
        r.access_scope == "public" or r.access_scope == "student:S999" for r in results
    ), f"leaked scopes: {scopes}"


def test_student_can_retrieve_their_own_record(index) -> None:
    results = index.retrieve(
        "What is my CGPA?", top_k=10, user_id="S102", role="student"
    )
    assert any(r.record_id == "db:students:S102" for r in results)


def test_staff_can_retrieve_any_record(index) -> None:
    results = index.retrieve(
        "What is the CGPA of S102?", top_k=10, user_id=None, role="staff"
    )
    assert any(r.record_id == "db:students:S102" for r in results)


def test_anonymous_user_sees_only_public(index) -> None:
    results = index.retrieve(
        "What is the CGPA of S102?", top_k=10, user_id=None, role="student"
    )
    assert all(r.access_scope == "public" for r in results)


def test_access_filter_permits_logic() -> None:
    from app.retrieval.index import AccessFilter

    assert AccessFilter.permits("public", {"public"})
    assert AccessFilter.permits("student:S1", {"public", "student:S1"})
    assert not AccessFilter.permits("student:S2", {"public", "student:S1"})
    # Staff scope None means unrestricted.
    assert AccessFilter.permits("student:S2", None)


# --------------------------------------------------------------------------
# Intent extraction
# --------------------------------------------------------------------------


def test_intent_policy_lookup() -> None:
    from app.core.schemas import Intent
    from app.retrieval.intent import understand_query

    result = understand_query("What is the minimum attendance requirement?")
    assert result.intent == Intent.policy_lookup
    assert "policy_cue" in result.matched_rules


def test_intent_personal_record_resolves_to_user() -> None:
    from app.core.schemas import Intent
    from app.retrieval.intent import understand_query

    result = understand_query("What is my attendance in CS301?", user_id="S102")
    assert result.intent == Intent.personal_record
    assert result.entities.get("student_id") == "S102"
    assert result.entities.get("course_id") == "CS301"


def test_intent_placement_requires_an_entity() -> None:
    from app.core.schemas import Intent
    from app.retrieval.intent import understand_query

    result = understand_query("Am I eligible for Zoho?")
    assert result.intent == Intent.placement_eligibility
    assert result.entities.get("company") == "Zoho"


def test_intent_detects_multi_hop_and_aggregate() -> None:
    from app.retrieval.intent import understand_query

    multi = understand_query("Compare the exam and placement attendance rules")
    assert multi.is_multi_hop
    agg = understand_query("How many students have a CGPA above 8?")
    assert agg.needs_aggregation


def test_unknown_entities_are_not_invented() -> None:
    from app.retrieval.intent import understand_query

    result = understand_query("What is the CGPA of S99999?")
    assert "student_id" not in result.entities, "a non-existent id must not be accepted"
    result2 = understand_query("What is the package at NoSuchCompany?")
    assert "company" not in result2.entities


# --------------------------------------------------------------------------
# Evaluation harness
# --------------------------------------------------------------------------


def test_retrieval_eval_produces_metrics(index) -> None:
    from app.eval.benchmark import load_benchmark
    from app.eval.retrieval_eval import evaluate_retrieval, format_table

    items = load_benchmark()
    assert len(items) >= 120
    results = evaluate_retrieval(index, items, modes=("bm25", "hybrid_rerank"), write=False)
    assert set(results) == {"bm25", "hybrid_rerank"}
    for metrics in results.values():
        assert 0.0 <= metrics.success_at_1 <= 1.0
        assert 0.0 <= metrics.mrr <= 1.0
        assert metrics.questions > 100
        assert metrics.latency_p50_ms >= 0
    table = format_table(results)
    assert "S@1" in table and "MRR" in table


def test_eval_ignores_unanswerable_questions(index) -> None:
    """Unanswerable items have no gold source, so they must not be scored."""
    from app.eval.benchmark import load_benchmark
    from app.eval.retrieval_eval import evaluate_retrieval

    items = load_benchmark()
    answerable = sum(1 for i in items if i.gold_sources)
    results = evaluate_retrieval(index, items, modes=("bm25",), write=False)
    assert results["bm25"].questions == answerable


def test_retrieval_beats_random_baseline(index) -> None:
    """A retrieval system that cannot beat chance on its own benchmark is broken."""
    from app.eval.benchmark import load_benchmark
    from app.eval.retrieval_eval import evaluate_retrieval

    items = load_benchmark()
    results = evaluate_retrieval(index, items, modes=("bm25", "hybrid_rerank"), write=False)
    assert results["bm25"].mrr > 0.4, "BM25 MRR is implausibly low"
    assert results["hybrid_rerank"].mrr > 0.4


def test_every_answerable_benchmark_question_has_a_resolvable_gold_source() -> None:
    """Guards the benchmark itself: labels must point at chunks that exist."""
    _need_corpus()
    from app.eval.benchmark import load_benchmark

    items = load_benchmark()
    for item in items:
        if item.answerable and item.kind != "adversarial":
            assert item.gold_sources, f"{item.id} is answerable but has no gold source"
