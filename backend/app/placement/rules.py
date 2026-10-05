"""Deterministic eligibility rules.

Every check here is a plain comparison that reports ``{required, actual, pass,
gap}``. There is no model and no score threshold: eligibility is decided, not
predicted. Suitability scores only ever *rank* students who already passed these
rules, so a soft score can never admit someone the criteria reject.
"""

from __future__ import annotations

import json
from typing import Any

from ..core.schemas import Criterion

# Criteria that are a floor (``min_*`` on the role vs a ``students`` field).
# Kept as data so the UI can render the same order the engine evaluates.
_NUMERIC_CRITERIA = (
    ("cgpa", "cgpa", "min_cgpa"),
    ("attendance", "attendance_pct", "min_attendance_pct"),
    ("projects", "project_count", "min_project_count"),
    ("communication", "communication_score", "min_communication"),
)


def _load_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return []
    return value if value is not None else []


def evaluate(
    student: dict[str, Any],
    role: dict[str, Any],
    requirements: list[dict[str, Any]],
    skill_levels: dict[str, int],
    overrides: dict[str, Any] | None = None,
) -> tuple[bool, list[Criterion], list[str]]:
    """Evaluate one (student, role) pair.

    ``overrides`` replaces student attributes for a what-if run without touching
    the database. ``skill_levels`` is expected to already include any override.
    Returns ``(eligible, criteria, failing_names)``.
    """
    overrides = overrides or {}
    criteria: list[Criterion] = []
    blocking: list[str] = []

    def add(criterion: Criterion, *, is_blocking: bool = True) -> None:
        criteria.append(criterion)
        if is_blocking and not criterion.passed:
            blocking.append(criterion.name)

    def actual(field: str) -> Any:
        return overrides.get(field, student.get(field))

    # --- numeric floors ----------------------------------------------
    for name, field, threshold_field in _NUMERIC_CRITERIA:
        required = role.get(threshold_field)
        if required is None:
            continue
        value = actual(field)
        if value is None:
            add(Criterion(name=name, required=required, actual=None, passed=False,
                          gap=f"{name} is not recorded"))
            continue
        passed = float(value) >= float(required)
        add(Criterion(
            name=name, required=required, actual=value, passed=passed,
            gap=None if passed else f"below the required {required}",
        ))

    # --- backlogs (a ceiling, not a floor) ---------------------------
    max_backlogs = role.get("max_backlogs")
    if max_backlogs is not None:
        value = actual("backlogs")
        if value is None:
            add(Criterion(name="backlogs", required=f"<= {max_backlogs}", actual=None,
                          passed=False, gap="backlogs are not recorded"))
        else:
            passed = int(value) <= int(max_backlogs)
            add(Criterion(
                name="backlogs", required=f"<= {max_backlogs}", actual=value, passed=passed,
                gap=None if passed else f"{int(value) - int(max_backlogs)} over the limit",
            ))

    # --- department ---------------------------------------------------
    allowed = _load_json(role.get("allowed_departments"))
    if allowed:
        dept = student.get("department")
        passed = dept in allowed
        add(Criterion(
            name="department", required=allowed, actual=dept, passed=passed,
            gap=None if passed else "department is not on the eligibility list",
        ))

    # --- skills -------------------------------------------------------
    # A required skill below its level is blocking; a preferred one is reported
    # but never fails the student.
    for requirement in requirements:
        skill_id = requirement["skill_id"]
        min_level = int(requirement["min_level"])
        is_required = bool(requirement.get("is_required", 1))
        level = int(skill_levels.get(skill_id, 0))
        passed = level >= min_level
        gap_suffix = "" if is_required else " (preferred, not blocking)"
        add(
            Criterion(
                name=f"skill:{skill_id}",
                required=f"level {min_level}" + ("" if is_required else " (preferred)"),
                actual=f"level {level}",
                passed=passed,
                gap=None if passed else f"{skill_id} is {min_level - level} level(s) short{gap_suffix}",
            ),
            is_blocking=is_required,
        )

    return (not blocking), criteria, blocking
