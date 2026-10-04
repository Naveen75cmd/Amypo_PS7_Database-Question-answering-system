"""The answer pipeline: understand -> (tools | retrieve) -> generate -> verify.

Produces both the HTTP response and a trace whose steps correspond to real
pipeline stages with real timings. Every number in the trace is measured, never
decorative: the UI renders exactly these values.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..core.schemas import (
    AskResponse,
    Intent,
    Source,
    TraceClaim,
    TraceResponse,
    TraceStep,
)
from ..core.settings import settings
from ..db import execute
from ..grounding.verifier import GroundingReport, GroundingVerifier
from ..llm.client import LLMClient
from ..llm.prompts import (
    ContextBlock,
    build_abstention,
    build_answer_prompt,
    build_phrase_prompt,
    is_abstention,
    strip_prompt_echo,
)
from ..llm.tools import (
    ToolResult,
    describe_no_record,
    render_tool_answer,
    run_for_intent,
)
from ..retrieval.index import Retrieved, RetrievalIndex
from ..retrieval.intent import (
    QueryUnderstanding,
    is_structured_intent,
    understand_query,
)

log = logging.getLogger(__name__)


@dataclass
class Stage:
    """One measured pipeline stage."""

    id: str
    title: str
    started: float = field(default_factory=time.perf_counter)
    duration_ms: float = 0.0
    items: list[str] = field(default_factory=list)
    detail: str | None = None
    status: str = "done"

    def finish(self, **kwargs: Any) -> "Stage":
        self.duration_ms = round((time.perf_counter() - self.started) * 1000, 2)
        for key, value in kwargs.items():
            setattr(self, key, value)
        return self

    def to_model(self) -> TraceStep:
        return TraceStep(
            id=self.id,
            title=self.title,
            status=self.status,  # type: ignore[arg-type]
            detail=self.detail,
            items=self.items,
            duration_ms=self.duration_ms,
            started_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        )


@dataclass
class PipelineResult:
    """Everything the API and the trace endpoint need."""

    request_id: str
    question: str
    answer: str
    sources: list[Source]
    confidence: float
    abstained: bool
    degraded: bool
    intent: Intent
    entities: dict[str, Any]
    complexity: str | None
    understanding: QueryUnderstanding
    retrieval: list[dict[str, Any]]
    grounding: GroundingReport
    steps: list[Stage]
    latency_ms: float
    route: str | None = None
    estimated_cost: float | None = None
    reasoning: str | None = None
    used_tools: list[str] = field(default_factory=list)

    def to_response(self) -> AskResponse:
        return AskResponse(
            answer=self.answer,
            sources=self.sources,
            confidence=self.confidence,
            route=self.route,  # type: ignore[arg-type]
            trace_id=self.request_id,
            degraded=self.degraded,
            abstained=self.abstained,
            latency_ms=self.latency_ms,
            estimated_cost=self.estimated_cost,
        )

    def to_trace(self) -> TraceResponse:
        return TraceResponse(
            request_id=self.request_id,
            question=self.question,
            answer=self.answer,
            route=self.route,  # type: ignore[arg-type]
            confidence=self.confidence,
            abstained=self.abstained,
            degraded=self.degraded,
            intent=self.intent,
            entities=self.entities,
            complexity=self.complexity,  # type: ignore[arg-type]
            steps=[s.to_model() for s in self.steps],
            claims=[TraceClaim(**c.as_dict()) for c in self.grounding.claims],
            sources=self.sources,
            retrieval=self.retrieval,
            reasoning=self.reasoning,
            created_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        )


class AskPipeline:
    """Runs the local answering path. The router calls into this."""

    def __init__(
        self,
        index: RetrievalIndex,
        llm: LLMClient,
        verifier: GroundingVerifier,
    ) -> None:
        self.index = index
        self.llm = llm
        self.verifier = verifier

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def answer(
        self,
        question: str,
        user_id: str | None = None,
        role: str = "student",
        top_k: int | None = None,
        request_id: str | None = None,
        mode: str = "hybrid_rerank",
        force_extractive: bool = False,
    ) -> PipelineResult:
        """Answer a question, degrading gracefully rather than failing."""
        request_id = request_id or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        steps: list[Stage] = []

        # 1. Understand ---------------------------------------------------
        stage = Stage("understand", "Understood the question")
        understanding = understand_query(question, user_id=user_id, role=role)
        stage.finish(
            detail=understanding.summary(),
            items=[f"intent: {understanding.intent.value}"]
            + [f"{k}: {v}" for k, v in understanding.entities.items()]
            + ([f"rule: {r}" for r in understanding.matched_rules[:3]]),
        )
        steps.append(stage)

        # 2. Structured tools --------------------------------------------
        # The SQL path is a second door onto the same records the retriever
        # guards, so it needs the same access rule. A caller may only reach
        # their own student record unless they hold a staff role.
        stage = Stage("tools", "Checked structured records")
        tool_results: list[ToolResult] = []
        scoped_entities, denied_student = _scope_entities(
            understanding.entities, user_id, role
        )
        if not denied_student and understanding.intent in (
            Intent.personal_record,
            Intent.aggregate_stat,
            Intent.placement_eligibility,
            Intent.skill_gap,
            Intent.candidate_recommendation,
        ):
            tool_results = run_for_intent(understanding.intent, scoped_entities, question)
        used_tools = [r.template for r in tool_results if r.ok and r.has_rows]
        stage.finish(
            detail=(
                "another student's record was requested outside your access scope"
                if denied_student
                else f"{len(used_tools)} SQL template(s) returned rows"
                if used_tools else "no structured template applied"
            ),
            items=[f"{r.template}: {r.summary}" for r in tool_results if r.ok and r.has_rows][:6],
            status="done" if tool_results else "pending",
        )
        steps.append(stage)

        # 3. Retrieval ----------------------------------------------------
        stage = Stage("retrieve", "Retrieved passages")
        retrieved = self.index.retrieve(
            question, top_k=top_k or settings.final_top_k,
            user_id=user_id, role=role, mode=mode,  # type: ignore[arg-type]
        )
        allowed = _allowed_scopes(user_id, role)
        blocked = self._count_blocked(question, allowed)
        stage.finish(
            detail=(
                f"{len(retrieved)} passage(s); "
                f"{blocked} withheld by access scope"
            ),
            items=[
                f"{r.rank}. {r.record_id} (score {r.rerank_score:.3f})" for r in retrieved
            ],
            status="done" if retrieved else "failed",
        )
        steps.append(stage)

        # 4. Build evidence ----------------------------------------------
        context, row_evidence = self._build_evidence(retrieved, tool_results)

        # 5. Generate -----------------------------------------------------
        stage = Stage("generate", "Composed an answer")
        model = "template"
        degraded = False
        echo_removed = False

        # Structured intents are answered from the rows themselves. This is the
        # cheapest local path and the most trustworthy one: the sentence is built
        # from the authoritative values, so no model can misstate a number.
        template_answer = render_tool_answer(question, tool_results)
        if (
            not denied_student
            and not template_answer
            and is_structured_intent(understanding.intent)
        ):
            # No rows, but a concrete record was asked for: say so explicitly
            # instead of falling through and answering from unrelated passages.
            template_answer = describe_no_record(
                understanding.intent, understanding.entities, tool_results
            )
        if denied_student:
            answer_text = (
                "I could not find this in AMYPO's records. Records for other "
                "students are outside your access scope."
            )
            model = "access-control"
        elif template_answer:
            answer_text = template_answer
        elif force_extractive or not self.llm.healthy():
            answer_text = self.llm._stub_result(
                question, context, model="stub-extractive"
            ).text
            model = "stub-extractive"
            degraded = True
        elif row_evidence and not context:
            answer_text, model, degraded = self._phrase_rows(question, tool_results)
        else:
            answer_text, model, degraded = self._generate(question, context, tool_results)
            cleaned = strip_prompt_echo(answer_text)
            echo_removed = bool(answer_text) and cleaned != answer_text
            if cleaned:
                answer_text = cleaned

        stage.finish(
            detail=f"model: {model}" + (" (degraded)" if degraded else ""),
            items=([f"{len(context)} context block(s) supplied"]
                   + (["prompt echo removed"] if echo_removed else [])
                   + (["answered from SQL rows without the LLM"] if model == "template" else [])),
            status="done" if answer_text else "failed",
        )
        steps.append(stage)

        # 6. Verify ------------------------------------------------------
        stage = Stage("verify", "Verified the claims")
        report = self.verifier.verify(
            answer_text, context, question=question, evidence_override=row_evidence
        )
        stage.finish(
            detail=f"{report.summary()}; confidence {report.confidence:.2f}",
            items=[c.reason for c in report.claims if c.reason][:5],
            status="done" if report.supported_claims or report.abstained else "failed",
        )
        steps.append(stage)

        # 7. Abstain when we cannot stand behind the answer ---------------
        sources = self._sources(retrieved, tool_results)
        if report.abstained:
            # An explicit "no record" template answer is already a canonical
            # abstention; keep its useful detail rather than replacing it with
            # the generic sentence.
            if not is_abstention(answer_text):
                answer_text = build_abstention(context)
            report = GroundingReport(
                claims=report.claims, groundedness=report.groundedness,
                confidence=report.confidence, abstained=True,
                supported_claims=report.supported_claims,
                total_claims=report.total_claims,
                numeric_violations=report.numeric_violations,
            )

        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        result = PipelineResult(
            request_id=request_id,
            question=question,
            answer=answer_text,
            sources=sources,
            confidence=report.confidence,
            abstained=report.abstained,
            degraded=degraded,
            intent=understanding.intent,
            entities=understanding.entities,
            complexity=None,
            understanding=understanding,
            retrieval=[r.as_dict() for r in retrieved],
            grounding=report,
            steps=steps,
            latency_ms=latency_ms,
            used_tools=used_tools,
        )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _count_blocked(self, question: str, allowed: set[str] | None) -> int:
        """How many otherwise-relevant passages the access filter withheld.

        Surfaced in the trace because "you cannot see this" is information the
        user is entitled to, and it proves the filter is actually running.
        """
        if allowed is None:
            return 0
        try:
            unrestricted = self.index.retrieve(question, top_k=10, user_id=None, role="staff")
            restricted_ids = {
                r.record_id for r in self.index.retrieve(
                    question, top_k=10, user_id=None, role="student"
                )
            }
            return sum(1 for r in unrestricted if r.record_id not in restricted_ids)
        except Exception:  # pragma: no cover - never fail a request over a stat
            return 0

    def _build_evidence(
        self, retrieved: list[Retrieved], tool_results: list[ToolResult]
    ) -> tuple[list[ContextBlock], dict[int, str]]:
        """Assemble numbered context blocks from passages and SQL rows."""
        context: list[ContextBlock] = []
        row_evidence: dict[int, str] = {}
        marker = 1

        for result in retrieved:
            context.append(
                ContextBlock(
                    index=marker,
                    record_id=result.record_id,
                    text=result.text,
                    title=result.title,
                    updated_at=result.updated_at,
                )
            )
            marker += 1

        # SQL rows become additional, authoritative evidence.
        for result in tool_results:
            if not result.ok or not result.has_rows:
                continue
            for row in result.rows[:6]:
                text = ", ".join(f"{k}: {v}" for k, v in row.items() if v is not None)
                record_id = result.record_ids[0] if result.record_ids else f"db:{result.template}"
                row_evidence[marker] = text
                context.append(
                    ContextBlock(
                        index=marker,
                        record_id=record_id,
                        text=text,
                        title=f"SQL result ({result.template})",
                    )
                )
                marker += 1
                if marker > 24:  # keep the prompt inside the context window
                    break

        return context, row_evidence

    def _generate(
        self, question: str, context: list[ContextBlock], tool_results: list[ToolResult]
    ) -> tuple[str, str, bool]:
        if not context:
            return "", "none", False
        system, user = build_answer_prompt(question, context)
        result = self.llm.generate(user, system=system, context=context, question=question)
        return result.text, result.model, result.stub

    def _phrase_rows(
        self, question: str, tool_results: list[ToolResult]
    ) -> tuple[str, str, bool]:
        """Phrase SQL rows without any retrieved passage."""
        rows: list[dict[str, Any]] = []
        markers: list[str] = []
        for result in tool_results:
            if not result.ok:
                continue
            for index, row in enumerate(result.rows[:6], start=len(rows) + 1):
                rows.append(row)
                markers.append(f"[S{index}]")
        if not rows:
            return "", "none", False
        system, user = build_phrase_prompt(question, rows, markers)
        result = self.llm.generate(user, system=system, context=[], question=question)
        return result.text, result.model, result.stub

    def _sources(
        self, retrieved: list[Retrieved], tool_results: list[ToolResult]
    ) -> list[Source]:
        """Citations in order of use, de-duplicated.

        Structured rows come first because a template answer is rendered from
        them: the row is the evidence the verifier checked the sentence against,
        so it is the primary citation. Retrieved passages follow.
        """
        sources: list[Source] = []
        seen: set[str] = set()

        for tool in tool_results:
            if not tool.ok or not tool.has_rows:
                continue
            for record_id, row in zip(tool.record_ids or [], tool.rows[:6]):
                if record_id in seen:
                    continue
                seen.add(record_id)
                sources.append(
                    Source(
                        record_id=record_id,
                        snippet=_clip(
                            ", ".join(f"{k}: {v}" for k, v in row.items() if v is not None),
                            settings.snippet_max_chars,
                        ),
                    )
                )

        for result in retrieved:
            if result.record_id in seen:
                continue
            seen.add(result.record_id)
            sources.append(
                Source(
                    record_id=result.record_id,
                    snippet=_clip(result.text, settings.snippet_max_chars),
                )
            )
        return sources

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    def persist(result: PipelineResult, user_id: str | None, role: str) -> None:
        """Write the query log row the trace endpoint reads back."""
        try:
            execute(
                """
                INSERT OR REPLACE INTO query_log
                    (request_id, question, user_id, role, intent, route, answer,
                     confidence, groundedness, abstained, degraded, latency_ms,
                     estimated_cost, trace_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.request_id,
                    result.question,
                    user_id,
                    role,
                    result.intent.value,
                    result.route,
                    result.answer,
                    result.confidence,
                    result.grounding.groundedness,
                    1 if result.abstained else 0,
                    1 if result.degraded else 0,
                    result.latency_ms,
                    result.estimated_cost,
                    result.to_trace().model_dump_json(),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
        except Exception as exc:  # pragma: no cover - logging must not break a request
            log.warning("could not persist query log: %s", exc)


def _allowed_scopes(user_id: str | None, role: str) -> set[str] | None:
    from ..retrieval.index import AccessFilter

    return AccessFilter.allowed_scopes(user_id, role)


def _scope_entities(
    entities: dict[str, Any], user_id: str | None, role: str
) -> tuple[dict[str, Any], bool]:
    """Drop a student id the caller is not allowed to read.

    Returns ``(entities, denied)``. ``denied`` is True only when a student id was
    explicitly requested and removed, so the pipeline can say plainly that the
    record is out of scope rather than pretending it does not exist.
    """
    if role in settings.staff_roles:
        return entities, False
    student_id = entities.get("student_id")
    if student_id and student_id != user_id:
        return {k: v for k, v in entities.items() if k != "student_id"}, True
    return entities, False


def _clip(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip() + "…"


def load_trace(request_id: str) -> TraceResponse | None:
    """Read a persisted trace back from the query log."""
    from ..db import query_one

    row = query_one("SELECT trace_json FROM query_log WHERE request_id = ?", (request_id,))
    if not row or not row["trace_json"]:
        return None
    try:
        return TraceResponse.model_validate_json(row["trace_json"])
    except Exception as exc:  # pragma: no cover
        log.warning("stored trace for %s is unreadable: %s", request_id, exc)
        return None
