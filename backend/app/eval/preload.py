"""Predictive cache pre-warming (Phase 8, item 5).

The demo's headline number is a near-zero-cost cache hit. Hitting that by
*waiting* for users to repeat themselves is luck, so the questions AMYPO has
already seen (the historical query log) are warmed into the semantic cache at
ingest time — exactly when the brief says the answers are known and cheapest to
compute.

Pre-warming never bypasses the pipeline: it calls the same ``answer_fn`` the
live path uses, so a warmed entry is indistinguishable from one earned by a real
question, and it goes through the same ``cache.store`` with the same scope and
source hashes. A warm entry that skipped grounding would be a shortcut for a
demo that is entirely about grounding.

Warming is also bounded (``settings.cache_prewarm_n``) and best-effort: one
failure must never fail an ingest, so every question is wrapped and a failure is
counted rather than raised.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ..core.settings import settings

log = logging.getLogger(__name__)

# answer_fn(question) -> (answer, sources, confidence) or None when it cannot
# answer. Returning None skips the question instead of caching a non-answer.
AnswerFn = Callable[[str], tuple[str, list[dict], float] | None]


def preload_cache(
    cache: Any,
    answer_fn: AnswerFn | None = None,
    questions: list[str] | None = None,
    top_n: int | None = None,
    access_scope: str = "public",
) -> dict[str, Any]:
    """Warm the cache for the most-asked historical questions.

    ``access_scope`` must be the scope the entry will be *looked up* under
    (``router.engine.cache_scope``); a warm entry filed anywhere else is never
    served, which is the difference between a cache-hit demo and a warm-up that
    silently does nothing.

    Returns a small report so the dashboard can show the warm run happened:
    ``{"attempted", "warmed", "already_warm", "failed", "skipped"}``.
    """
    if questions is None:
        from .benchmark import load_query_history

        questions = load_query_history()

    limit = settings.cache_prewarm_n if top_n is None else top_n
    if limit <= 0 or not questions:
        return {"attempted": 0, "warmed": 0, "already_warm": 0, "failed": 0,
                "skipped": len(questions)}

    if answer_fn is None:
        # Nothing to compute with: warming without an answer path would only
        # prove that lookups miss. Report honestly rather than pretend.
        return {"attempted": 0, "warmed": 0, "already_warm": 0, "failed": 0,
                "skipped": len(questions[:limit])}

    report = {"attempted": 0, "warmed": 0, "already_warm": 0, "failed": 0,
              "skipped": 0}

    for question in dict.fromkeys(questions[:limit]):  # de-dup, keep order
        report["attempted"] += 1
        try:
            # One scope per run: an answer computed for a student must never be
            # stored under a key another scope reads.
            if cache.lookup(question, access_scope=access_scope) is not None:
                report["already_warm"] += 1
                continue
            produced = answer_fn(question)
            if not produced:
                report["skipped"] += 1
                continue
            answer, sources, confidence = produced
            if not answer:
                report["skipped"] += 1
                continue
            cache.store(
                question,
                answer,
                sources,
                confidence,
                access_scope=access_scope,
            )
            report["warmed"] += 1
        except Exception as exc:  # pragma: no cover - ingest must not fail
            report["failed"] += 1
            log.warning("pre-warm failed for %r: %s", question, exc)

    if report["warmed"]:
        log.info(
            "pre-warmed %d/%d historical questions into the cache",
            report["warmed"],
            report["attempted"],
        )
    return report


def warm_from_history(cache: Any, answer_fn: AnswerFn | None = None) -> dict[str, Any]:
    """Warm a supplied cache: kept for tests and callers that own both pieces."""
    return preload_cache(cache, answer_fn=answer_fn)


def warm_from_pipeline() -> dict[str, Any]:
    """Ingest-time entry point: warm the live cache through the live pipeline.

    This is what makes item 5 real rather than a library nobody calls. It runs
    after ingest, when the corpus the historical questions are about is finally
    in place, and answers each question with the same ``AskPipeline`` the user's
    requests use — so a warm entry carries real grounding and real source
    hashes, and is served like any other hit.

    Bounded by ``settings.cache_prewarm_n`` (0 disables), best-effort, and never
    allowed to fail an ingest: a warm run that breaks is a missed optimisation,
    not a broken build.
    """
    from ..api.ask_service import AskPipeline
    from ..core.container import get_container

    if settings.cache_prewarm_n <= 0:
        return {"attempted": 0, "warmed": 0, "already_warm": 0, "failed": 0,
                "skipped": 0}

    container = get_container()
    cache = container.get("cache")
    pipeline = AskPipeline(
        index=container.get("index"),
        llm=container.get("llm"),
        verifier=container.get("verifier"),
    )

    totals = {"attempted": 0, "warmed": 0, "already_warm": 0, "failed": 0, "skipped": 0}
    for scope in settings.cache_prewarm_scopes:
        user_id, role = scope_identity(scope)

        def answer_fn(
            question: str, user_id: str | None = user_id, role: str = role
        ) -> tuple[str, list[dict], float] | None:
            result = pipeline.answer(question, user_id=user_id, role=role)
            # Only real answers are worth a cache entry. Warming an abstention
            # would teach the demo that unanswerable questions are cheap, which
            # is the opposite of the lesson.
            if result is None or not result.answer or result.abstained:
                return None
            return (
                result.answer,
                [source.model_dump() for source in result.sources],
                float(result.confidence),
            )

        report = preload_cache(cache, answer_fn=answer_fn, access_scope=scope)
        for key in totals:
            totals[key] += int(report.get(key, 0))
    totals["scopes"] = len(settings.cache_prewarm_scopes)
    return totals


def scope_identity(scope: str) -> tuple[str | None, str]:
    """Map a cache scope back to the (user_id, role) that looks it up.

    ``router.engine.cache_scope`` is the inverse of this; the two must agree or
    a warmed entry would be filed where nobody looks.
    """
    if scope == "staff":
        return None, "staff"
    if scope.startswith("student:"):
        return scope.split(":", 1)[1], "student"
    return None, "student"  # the anonymous/public scope
