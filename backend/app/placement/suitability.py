"""Suitability scoring for ranking students who already passed the rules.

Suitability never decides eligibility; it only orders students the criteria have
already accepted. Every component is a transparent 0..1 number with a named
weight, so the UI can show *why* one candidate outranks another instead of
presenting a single opaque score.
"""

from __future__ import annotations

import json
from typing import Any

# Component weights come from ``company_roles.weights`` (per role). These are the
# fallbacks if a role row has no weights recorded.
DEFAULT_WEIGHTS: dict[str, float] = {
    "skill_match": 0.40,
    "project_relevance": 0.20,
    "performance_trend": 0.15,
    "coding": 0.15,
    "communication": 0.10,
}

_COMPONENTS = (
    "skill_match",
    "project_relevance",
    "performance_trend",
    "coding",
    "communication",
)


def load_weights(role: dict[str, Any]) -> dict[str, float]:
    raw = role.get("weights")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = None
    if not isinstance(raw, dict) or not raw:
        return dict(DEFAULT_WEIGHTS)
    # Keep only known components; renormalise so the weights sum to 1.
    cleaned = {k: float(v) for k, v in raw.items() if k in _COMPONENTS}
    total = sum(cleaned.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in cleaned.items()}


def _skill_match(requirements: list[dict[str, Any]], skill_levels: dict[str, int]) -> float:
    if not requirements:
        return 1.0
    weighted = 0.0
    total_weight = 0.0
    for requirement in requirements:
        min_level = int(requirement["min_level"]) or 1
        level = int(skill_levels.get(requirement["skill_id"], 0))
        importance = float(requirement.get("importance", 1.0))
        weighted += min(level / min_level, 1.0) * importance
        total_weight += importance
    return weighted / total_weight if total_weight else 1.0


def _project_relevance(enrollments: list[dict[str, Any]], student: dict[str, Any]) -> float:
    grades = [float(e["project_grade"]) for e in enrollments if e.get("project_grade") is not None]
    if grades:
        return max(0.0, min(1.0, (sum(grades) / len(grades)) / 100.0))
    # No project grades recorded: fall back to how many projects were completed.
    count = int(student.get("project_count") or 0)
    return max(0.0, min(1.0, count / 4.0))


def _performance_trend(enrollments: list[dict[str, Any]]) -> float:
    """Improving vs declining grades, as a 0..1 score (0.5 is flat)."""
    scored = [
        (int(e["semester"]), float(e["score"]))
        for e in enrollments
        if e.get("score") is not None and e.get("semester") is not None
    ]
    if len(scored) < 2:
        return 0.5
    scored.sort()
    midpoint = len(scored) // 2
    earlier = [s for _, s in scored[:midpoint]]
    later = [s for _, s in scored[midpoint:]]
    if not earlier or not later:
        return 0.5
    delta = (sum(later) / len(later)) - (sum(earlier) / len(earlier))
    # +/-(10 marks) maps to roughly the top/bottom of the range.
    return max(0.0, min(1.0, 0.5 + delta / 20.0))


def _coding(enrollments: list[dict[str, Any]]) -> float:
    scores = [float(e["coding_score"]) for e in enrollments if e.get("coding_score") is not None]
    if not scores:
        return 0.0
    return max(0.0, min(1.0, (sum(scores) / len(scores)) / 100.0))


def _communication(student: dict[str, Any]) -> float:
    value = student.get("communication_score")
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value) / 5.0))


def score_student(
    student: dict[str, Any],
    role: dict[str, Any],
    requirements: list[dict[str, Any]],
    skill_levels: dict[str, int],
    enrollments: list[dict[str, Any]],
) -> tuple[float, list[dict[str, Any]]]:
    """Return ``(score_0_to_100, factors)`` with factors sorted by contribution."""
    weights = load_weights(role)
    values = {
        "skill_match": _skill_match(requirements, skill_levels),
        "project_relevance": _project_relevance(enrollments, student),
        "performance_trend": _performance_trend(enrollments),
        "coding": _coding(enrollments),
        "communication": _communication(student),
    }
    factors = [
        {
            "name": name,
            "value": round(values[name], 4),
            "weight": round(weights.get(name, 0.0), 4),
            "contribution": round(values[name] * weights.get(name, 0.0), 4),
        }
        for name in _COMPONENTS
    ]
    factors.sort(key=lambda f: f["contribution"], reverse=True)
    total = sum(f["contribution"] for f in factors)
    return round(total * 100.0, 2), factors
