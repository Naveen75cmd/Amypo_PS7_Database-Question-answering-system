"""Natural-language placement answers for the ``/ask`` path.

The placement engine produces structured results; this module phrases them into
citable sentences for the ask pipeline. Two rules keep the answer honest:

* every number in the text appears verbatim in a cited record, because the
  grounding verifier rejects any number it cannot find in the evidence;
* computed suitability scores never appear in the prose — they are not recorded
  facts, and stating them here would make the verifier's numeric check pass on
  the engine's own arithmetic rather than on the data.

Each fact is its own short sentence citing the record it came from, so the
verifier can check every claim against its own evidence. The full, scored
detail (suitability, factor breakdowns, closest misses) lives in the
``/placement/*`` endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.schemas import Intent, Source
from ..ingest.chunking import db_record_id
from .engine import _role_snippet, _student_snippet, PlacementEngine

# How many roles to name in an open "what am I eligible for" answer.
_MAX_OPEN_ROLES = 8


@dataclass
class PlacementAnswer:
    text: str
    sources: list[Source] = field(default_factory=list)
    evidence: dict[int, str] = field(default_factory=dict)
    # A cohort answer ranges over many students' records, so the pipeline
    # records it in the cohort audit log like the /placement endpoints do.
    cohort: bool = False
    result_count: int = 0


class _Evidence:
    """Assigns ``[S<n>]`` markers and collects the matching sources/evidence."""

    def __init__(self) -> None:
        self.sources: list[Source] = []
        self.evidence: dict[int, str] = {}
        self._by_record: dict[str, int] = {}

    def add(self, record_id: str, snippet: str, evidence_text: str | None = None) -> str:
        if record_id in self._by_record:
            return f"[S{self._by_record[record_id]}]"
        index = len(self.sources) + 1
        self._by_record[record_id] = index
        self.sources.append(Source(record_id=record_id, snippet=snippet[:240]))
        self.evidence[index] = (evidence_text or snippet)[:600]
        return f"[S{index}]"


def _student_evidence(student: dict[str, Any]) -> str:
    return f"student_id: {student['student_id']}, " + _student_snippet(student)


def _role_evidence(role: dict[str, Any]) -> str:
    """Role evidence: the numeric thresholds ARE the eligibility criteria."""
    return (
        f"{role.get('company')} {role.get('title')} eligibility criteria: "
        + _role_snippet(role)
        + _departments_evidence(role)
    )


def _departments_evidence(role: dict[str, Any]) -> str:
    allowed = role.get("allowed_departments")
    if isinstance(allowed, str):
        import json

        try:
            allowed = json.loads(allowed)
        except (TypeError, ValueError):
            allowed = []
    if not allowed:
        return ""
    return f", allowed department list: {', '.join(str(d) for d in allowed)}"


def _skill_evidence_text(name: str, skill_id: str, current: int, required: int) -> str:
    return f"{name} ({skill_id}): current level {current}, required level {required}"


def _is_placement_intent(intent: Intent) -> bool:
    return intent in (
        Intent.placement_eligibility,
        Intent.skill_gap,
        Intent.candidate_recommendation,
    )


def build(
    intent: Intent,
    entities: dict[str, Any],
    question: str,
    engine: PlacementEngine,
    user_id: str | None = None,
    role: str = "student",
) -> PlacementAnswer | None:
    """Build an answer, or return None when the question cannot be served.

    Returns None rather than guessing when a needed entity is missing, so the
    pipeline falls back to its normal retrieval/abstention path.
    """
    if not _is_placement_intent(intent):
        return None

    student_id = entities.get("student_id")
    company = entities.get("company")
    role_title = entities.get("role")

    if intent == Intent.skill_gap:
        if not student_id:
            return None
        return _skill_gap_answer(engine, student_id, company, role_title)
    if intent == Intent.candidate_recommendation:
        if not company and not role_title:
            return None
        return _match_answer(engine, company, role_title)
    # placement_eligibility
    if student_id:
        return _eligibility_answer(engine, student_id, company, role_title)
    if company or role_title:
        return _match_answer(engine, company, role_title)
    return None


def _eligibility_answer(
    engine: PlacementEngine, student_id: str, company: str | None, role_title: str | None
) -> PlacementAnswer | None:
    results = engine.eligibility(student_id=student_id, company=company, role=role_title)
    if not results:
        return None
    student = engine._student(student_id)
    if student is None:
        return None

    ev = _Evidence()
    stu_marker = ev.add(
        db_record_id("students", student_id),
        _student_snippet(student),
        _student_evidence(student),
    )

    if company or role_title:
        # A narrowed question reports that role's verdict plus what went wrong.
        result = results[0]
        target = f"{result.company} {result.role}"
        role = engine.resolve_role(role_id=result.role_id)
        role_marker = (
            ev.add(
                db_record_id("company_roles", result.role_id),
                _role_snippet(role),
                _role_evidence(role),
            )
            if role
            else ""
        )
        if result.eligible:
            text = (
                f"{student['name']} ({student_id}) is eligible for "
                f"{target} {role_marker}{stu_marker}."
            )
            return PlacementAnswer(text=text, sources=ev.sources, evidence=ev.evidence)

        sentences = [
            f"{student['name']} ({student_id}) is not eligible for "
            f"{target} {role_marker}{stu_marker}."
        ]
        sentences.extend(_failing_sentences(ev, engine, result, student))
        return PlacementAnswer(text=" ".join(sentences), sources=ev.sources, evidence=ev.evidence)

    # Open question: name the roles the student qualifies for.
    eligible = [r for r in results if r.eligible][:_MAX_OPEN_ROLES]
    if not eligible:
        return PlacementAnswer(
            text=(
                f"{student['name']} ({student_id}) does not currently meet the "
                f"eligibility criteria for any role on record {stu_marker}."
            ),
            sources=ev.sources,
            evidence=ev.evidence,
        )

    sentences = [
        f"{student['name']} ({student_id}) is eligible for these roles {stu_marker}."
    ]
    for result in eligible:
        role = engine.resolve_role(role_id=result.role_id)
        marker = (
            ev.add(
                db_record_id("company_roles", result.role_id),
                _role_snippet(role),
                _role_evidence(role),
            )
            if role
            else ""
        )
        sentences.append(f"Eligible: {result.company} {result.role} {marker}.")
    return PlacementAnswer(text=" ".join(sentences), sources=ev.sources, evidence=ev.evidence)


def _failing_sentences(
    ev: _Evidence, engine: PlacementEngine, result: Any, student: dict[str, Any]
) -> list[str]:
    """One citable sentence per blocking criterion the student failed.

    Only blocking criteria are phrased here: preferred-skill shortfalls never
    change the verdict, and the /placement endpoints report them in full.
    """
    target = f"{result.company} {result.role}"
    skill_names = {
        r["skill_id"]: r["skill_name"] for r in engine._requirements(result.role_id)
    }
    sentences: list[str] = []
    for criterion in result.criteria:
        if criterion.passed or criterion.name.startswith("skill:") and _is_preferred(criterion):
            continue
        name = criterion.name
        if name.startswith("skill:"):
            skill_id = name.split(":", 1)[1]
            current = _level_of(criterion.actual)
            required = _level_of(criterion.required)
            display = skill_names.get(skill_id, skill_id)
            marker = ev.add(
                db_record_id("skills", skill_id),
                f"{display}: required level {required}",
                _skill_evidence_text(display, skill_id, current, required),
            )
            sentences.append(
                f"For {target}, {skill_id} is short of the required level: "
                f"current level {current}, required level {required} {marker}."
            )
        elif name in ("cgpa", "attendance", "projects", "communication"):
            marker = f"[S{ev._by_record[db_record_id('company_roles', result.role_id)]}]"
            stu = f"[S{ev._by_record[db_record_id('students', student['student_id'])]}]"
            sentences.append(
                f"For {target}, {name} {criterion.actual} is below the required "
                f"{criterion.required} {marker}{stu}."
            )
        elif name == "backlogs":
            marker = f"[S{ev._by_record[db_record_id('company_roles', result.role_id)]}]"
            stu = f"[S{ev._by_record[db_record_id('students', student['student_id'])]}]"
            sentences.append(
                f"For {target}, backlogs {criterion.actual} exceed the limit of "
                f"{_max_backlogs(result)} {marker}{stu}."
            )
        else:  # department
            marker = f"[S{ev._by_record[db_record_id('company_roles', result.role_id)]}]"
            stu = f"[S{ev._by_record[db_record_id('students', student['student_id'])]}]"
            sentences.append(
                f"For {target}, the department {criterion.actual} is not on the "
                f"allowed department list {marker}{stu}."
            )
    return sentences


def _is_preferred(criterion: Any) -> bool:
    return "preferred" in str(criterion.required)


def _level_of(value: Any) -> int:
    """Pull the integer level out of strings like ``level 3 (preferred)``."""
    import re

    match = re.search(r"(\d+)", str(value))
    return int(match.group(1)) if match else 0


def _max_backlogs(result: Any) -> str:
    for criterion in result.criteria:
        if criterion.name == "backlogs":
            text = str(criterion.required)
            return text.replace("<=", "").strip()
    return "the role's limit"


def _skill_gap_answer(
    engine: PlacementEngine, student_id: str, company: str | None, role_title: str | None
) -> PlacementAnswer | None:
    report = engine.skill_gap(student_id, company=company, role=role_title)
    if report is None:
        return None
    student = engine._student(student_id)
    if student is None:
        return None

    ev = _Evidence()
    stu_marker = ev.add(
        db_record_id("students", student_id),
        _student_snippet(student),
        _student_evidence(student),
    )
    role = engine.resolve_role(company, role_title)
    role_marker = (
        ev.add(
            db_record_id("company_roles", role["role_id"]),
            _role_snippet(role),
            _role_evidence(role),
        )
        if role
        else ""
    )

    target = f"{report.company} {report.target_role}" if report.target_role else "the target role"
    blocking = [g for g in report.gaps if g.severity == "blocking"]

    sentences = [
        f"{student['name']} ({student_id}) is missing these for {target} "
        f"{role_marker}{stu_marker}."
    ]
    for gap in blocking:
        skill_id = getattr(gap, "skill_id", None) or gap.skill.lower().replace(" ", "")
        marker = ev.add(
            db_record_id("skills", skill_id),
            f"{gap.skill}: required level {gap.required_level}",
            _skill_evidence_text(gap.skill, skill_id, gap.current_level, gap.required_level),
        )
        sentences.append(
            f"For {target}, {gap.skill} is short of the required level: "
            f"current level {gap.current_level}, required level "
            f"{gap.required_level} {marker}."
        )
    if report.learning_path:
        step = report.learning_path[0]
        if step.record_id:
            effort_text = f"estimated effort {step.effort_weeks} weeks"
            evidence_text = f"{step.title}. {step.snippet or ''}. {effort_text}"
            marker = ev.add(step.record_id, step.title, evidence_text)
            sentences.append(
                f"First step for {target}: {step.title} ({effort_text}) {marker}."
            )
    return PlacementAnswer(text=" ".join(sentences), sources=ev.sources, evidence=ev.evidence)


def _match_answer(
    engine: PlacementEngine, company: str | None, role_title: str | None
) -> PlacementAnswer | None:
    match = engine.match(company=company, role=role_title, top_n=5)
    if match is None:
        return None
    ev = _Evidence()
    role = engine.resolve_role(role_id=match.role_id)
    role_marker = (
        ev.add(
            db_record_id("company_roles", match.role_id),
            _role_snippet(role),
            _role_evidence(role),
        )
        if role
        else ""
    )
    if not match.candidates:
        text = (
            f"No student meets the eligibility criteria for "
            f"{match.company} {match.role} {role_marker}."
        )
        return PlacementAnswer(
            text=text, sources=ev.sources, evidence=ev.evidence,
            cohort=True, result_count=0,
        )

    # One sentence per candidate: each claim then cites the student record it
    # names, which keeps lexical overlap high enough for the verifier.
    sentences = [
        f"Students eligible for {match.company} {match.role} {role_marker}."
    ]
    for candidate in match.candidates:
        student = engine._student(candidate.student_id)
        marker = ev.add(
            db_record_id("students", candidate.student_id),
            _student_snippet(student) if student else candidate.student_name,
            _student_evidence(student) if student else candidate.student_name,
        )
        sentences.append(
            f"{candidate.student_name} ({candidate.student_id}) is eligible for "
            f"{match.company} {match.role} {marker}."
        )
    return PlacementAnswer(
        text=" ".join(sentences), sources=ev.sources, evidence=ev.evidence,
        cohort=True, result_count=len(match.candidates),
    )
