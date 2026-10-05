"""Skill-gap analysis and learning paths.

Gaps come straight from the eligibility criteria: for each role requirement the
student does not meet, report the shortfall and suggest a citable way to close
it. Suggestions are sourced from the ingested catalogue (course manuals and
skill records) rather than invented, so every recommendation carries a
``record_id`` the user can open.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.schemas import LearningStep, SkillGapItem, Source
from ..db import query

# How long closing one level of a gap is estimated to take, in weeks. A rough,
# stated assumption rather than a hidden constant.
_WEEKS_PER_LEVEL = 1.5
_MAX_SUGGESTIONS = 3


@dataclass
class GapReport:
    gaps: list[SkillGapItem] = field(default_factory=list)
    learning_path: list[LearningStep] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)


def _severity(current: int, required: int, is_required: bool) -> str:
    if current >= required:
        return "ok"
    if is_required:
        return "blocking"
    return "weak"


def _catalogue_suggestions(skill_name: str, skill_id: str) -> list[dict[str, Any]]:
    """Citable catalogue records that teach this skill.

    Reads the chunk table directly (no embeddings) so suggestions are
    deterministic and always resolvable to a real record id.
    """
    try:
        rows = query(
            """
            SELECT record_id, title, text
            FROM chunks
            WHERE access_scope = 'public'
              AND record_id LIKE 'doc:%'
              AND (text LIKE ? OR title LIKE ?)
            ORDER BY (record_id LIKE 'doc:course-manual%') DESC, record_id
            LIMIT ?
            """,
            (f"%{skill_name}%", f"%{skill_name}%", _MAX_SUGGESTIONS),
        )
    except Exception:  # pragma: no cover - a missing index must not break a plan
        return []

    suggestions: list[dict[str, Any]] = []
    for row in rows:
        text = " ".join((row.get("text") or "").split())
        suggestions.append(
            {
                "kind": "module",
                "record_id": row["record_id"],
                "title": row.get("title") or skill_name,
                "snippet": text[:240],
            }
        )
    if not suggestions:
        suggestions.append(
            {
                "kind": "skill",
                "record_id": f"db:skills:{skill_id}",
                "title": f"Practise {skill_name}",
                "snippet": f"No catalogue module found for {skill_name}; practise it directly.",
            }
        )
    return suggestions


def analyse(
    requirements: list[dict[str, Any]],
    skill_levels: dict[str, int],
) -> GapReport:
    """Build gaps and an ordered learning path for a target role."""
    report = GapReport()
    seen_records: set[str] = set()
    pending: list[tuple[int, dict[str, Any], SkillGapItem]] = []

    for requirement in requirements:
        skill_id = requirement["skill_id"]
        name = requirement.get("skill_name") or skill_id
        category = requirement.get("category") or "skill"
        required = int(requirement["min_level"])
        current = int(skill_levels.get(skill_id, 0))
        is_required = bool(requirement.get("is_required", 1))
        severity = _severity(current, required, is_required)

        item = SkillGapItem(
            skill=name,
            skill_id=str(skill_id),
            category=category,
            current_level=current,
            required_level=required,
            severity=severity,  # type: ignore[arg-type]
            suggestions=[] if severity == "ok" else _catalogue_suggestions(name, skill_id),
        )
        report.gaps.append(item)

        if severity == "ok":
            continue

        for suggestion in item.suggestions:
            record_id = suggestion.get("record_id")
            if record_id and record_id not in seen_records:
                seen_records.add(record_id)
                report.sources.append(
                    Source(record_id=record_id, snippet=(suggestion.get("snippet") or "")[:240])
                )

        pending.append((len(pending), requirement, item))

    # Blocking gaps first, then by importance, then by how far behind the student
    # is; ties keep requirement order so the path is stable across runs.
    def _sort_key(entry: tuple[int, dict[str, Any], SkillGapItem]) -> tuple:
        order, requirement, item = entry
        blocking = 0 if item.severity == "blocking" else 1
        gap = max(0, item.required_level - item.current_level)
        return (blocking, gap == 0, gap, -float(requirement.get("importance", 1.0)), order)

    for position, (_, _, item) in enumerate(sorted(pending, key=_sort_key), start=1):
        shortfall = max(0, item.required_level - item.current_level)
        effort = round(max(1.0, shortfall * _WEEKS_PER_LEVEL), 1)
        top = item.suggestions[0] if item.suggestions else None
        report.learning_path.append(
            LearningStep(
                order=position,
                title=f"Reach level {item.required_level} in {item.skill}",
                kind="module" if (top and top.get("kind") == "module") else "skill",
                effort_weeks=effort,
                record_id=top.get("record_id") if top else None,
                snippet=top.get("snippet") if top else None,
            )
        )

    return report
