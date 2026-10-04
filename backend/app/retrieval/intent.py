"""Rule-based query understanding.

Deliberately transparent: every classification can be traced to a rule, and the
trace is shown to the user. Entities are matched against the actual database
rather than guessed from patterns, so a hallucinated student id cannot occur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..core.schemas import Intent

_COURSE_RE = re.compile(r"\b([A-Z]{2}\d{3})\b")
_STUDENT_RE = re.compile(r"\b(S\d{3,})\b")
_PERCENT_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*%")
_NUMBER_RE = re.compile(r"\b(\d+(?:\.\d+)?)\b")

_MULTI_HOP_CUES = (
    "compare", "and also", "both", "as well as", "difference between",
    "which is stricter", "on the other hand", "versus", "vs ", "together",
)
_AGGREGATE_CUES = (
    "how many", "average", "top ", "highest", "lowest", "count", "total",
    "list all", "rank", "distribution",
)
_POLICY_CUES = (
    "policy", "rule", "allowed", "permitted", "requirement", "eligible",
    "minimum", "maximum", "fine", "fee", "deadline", "curfew", "procedure",
    "what happens if", "can i", "am i allowed", "is it allowed",
)
_PERSONAL_CUES = (
    "my ", "mine", "i have", "do i", "am i", "for me", "myself",
)
# Attributes that live on a student's own record. Naming a student id together
# with one of these is a record lookup even without the word "my": staff ask
# "What is the CGPA of S101?" exactly this way.
_PERSONAL_ATTRIBUTE_CUES = (
    "cgpa", "gpa", "attendance", "grade", "score", "marks", "backlog",
    "skill", "profile", "percent",
)
_PLACEMENT_CUES = (
    "eligible for", "eligibility", "placement", "drive", "recruiter",
    "company", "package", "lpa", "offer", "shortlist",
)
_SKILL_GAP_CUES = (
    "what am i missing", "skill gap", "improve my chances", "what should i learn",
    "prepare for", "learn for", "missing for",
)
_RECOMMEND_CUES = (
    "who is eligible", "top 5", "top 10", "recommend candidates", "best candidates",
    "rank candidates", "shortlist for", "candidates for",
)


@dataclass
class QueryUnderstanding:
    question: str
    intent: Intent
    entities: dict[str, Any] = field(default_factory=dict)
    is_multi_hop: bool = False
    needs_aggregation: bool = False
    is_personal: bool = False
    matched_rules: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.value,
            "entities": self.entities,
            "is_multi_hop": self.is_multi_hop,
            "needs_aggregation": self.needs_aggregation,
            "is_personal": self.is_personal,
            "matched_rules": self.matched_rules,
            "numbers": self.numbers,
        }

    def summary(self) -> str:
        """One-sentence explanation for the UI."""
        bits: list[str] = [f"intent={self.intent.value}"]
        if self.entities:
            rendered = ", ".join(f"{k}={v}" for k, v in self.entities.items())
            bits.append(f"entities: {rendered}")
        if self.is_multi_hop:
            bits.append("multi-hop")
        if self.needs_aggregation:
            bits.append("aggregate")
        return "; ".join(bits)


def _load_vocab() -> tuple[set[str], set[str], set[str]]:
    """Course codes, student ids and company/role names, read from the database."""
    from ..db import query

    courses: set[str] = set()
    students: set[str] = set()
    companies: set[str] = set()
    try:
        courses = {r["course_id"] for r in query("SELECT course_id FROM courses")}
        students = {r["student_id"] for r in query("SELECT student_id FROM students")}
        companies = {r["name"] for r in query("SELECT name FROM companies")}
    except Exception:
        pass
    return courses, students, companies


def understand_query(
    question: str,
    user_id: str | None = None,
    role: str = "student",
) -> QueryUnderstanding:
    lowered = question.lower()
    result = QueryUnderstanding(question=question, intent=Intent.general)

    courses, students, companies = _load_vocab()

    # --- entities -------------------------------------------------------
    course_match = _COURSE_RE.search(question)
    if course_match and (not courses or course_match.group(1) in courses):
        result.entities["course_id"] = course_match.group(1)
        result.matched_rules.append("course_code_pattern")

    student_match = _STUDENT_RE.search(question)
    if student_match and (not students or student_match.group(1) in students):
        result.entities["student_id"] = student_match.group(1)
        result.matched_rules.append("student_id_pattern")
    elif user_id and any(cue in lowered for cue in _PERSONAL_CUES):
        # "my attendance" from a logged-in student resolves to their own id.
        result.entities["student_id"] = user_id
        result.matched_rules.append("personal_pronoun_to_user_id")

    for name in sorted(companies, key=len, reverse=True):
        if name.lower() in lowered:
            result.entities["company"] = name
            result.matched_rules.append("company_name_match")
            break

    # Role titles are matched longest-first so "Power Programmer" beats "Programmer".
    role_rows = _role_titles()
    for title in role_rows:
        if title.lower() in lowered:
            result.entities["role"] = title
            result.matched_rules.append("role_title_match")
            break

    result.numbers = _NUMBER_RE.findall(question)
    if _PERCENT_RE.search(question):
        result.matched_rules.append("percent_literal")

    # --- signals --------------------------------------------------------
    result.is_multi_hop = any(cue in lowered for cue in _MULTI_HOP_CUES)
    if result.is_multi_hop:
        result.matched_rules.append("multi_hop_cue")
    result.needs_aggregation = any(cue in lowered for cue in _AGGREGATE_CUES)
    if result.needs_aggregation:
        result.matched_rules.append("aggregate_cue")
    result.is_personal = bool(
        any(cue in lowered for cue in _PERSONAL_CUES)
        or (user_id and "student_id" in result.entities and result.entities["student_id"] == user_id)
    )

    # --- intent ---------------------------------------------------------
    if any(cue in lowered for cue in _RECOMMEND_CUES) and "company" in result.entities:
        result.intent = Intent.candidate_recommendation
        result.matched_rules.append("recommendation_cue")
    elif any(cue in lowered for cue in _SKILL_GAP_CUES):
        result.intent = Intent.skill_gap
        result.matched_rules.append("skill_gap_cue")
    elif any(cue in lowered for cue in _PLACEMENT_CUES) and (
        "company" in result.entities or "role" in result.entities
    ):
        result.intent = Intent.placement_eligibility
        result.matched_rules.append("placement_cue_with_entity")
    elif "student_id" in result.entities and (
        result.is_personal
        or any(cue in lowered for cue in _PERSONAL_ATTRIBUTE_CUES)
    ):
        # A named student plus a record attribute is a lookup of that student's
        # record. Access control decides whether the caller may see it; the
        # intent itself does not depend on who is asking.
        result.intent = Intent.personal_record
        result.matched_rules.append("personal_with_student_id")
    elif result.needs_aggregation:
        result.intent = Intent.aggregate_stat
        result.matched_rules.append("aggregate_intent")
    elif any(cue in lowered for cue in _POLICY_CUES):
        result.intent = Intent.policy_lookup
        result.matched_rules.append("policy_cue")
    elif "company" in result.entities or "role" in result.entities:
        result.intent = Intent.placement_eligibility
        result.matched_rules.append("entity_only_placement")

    return result


def _role_titles() -> list[str]:
    from ..db import query

    try:
        titles = [r["title"] for r in query("SELECT DISTINCT title FROM company_roles")]
    except Exception:
        return []
    return sorted(titles, key=len, reverse=True)


def is_structured_intent(intent: Intent) -> bool:
    """Intents the SQL template catalogue can answer without the LLM."""
    return intent in {
        Intent.personal_record,
        Intent.aggregate_stat,
        Intent.placement_eligibility,
        Intent.skill_gap,
        Intent.candidate_recommendation,
    }
