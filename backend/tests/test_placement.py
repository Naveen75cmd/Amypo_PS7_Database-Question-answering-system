"""Phase 6 definition of done: the deterministic placement engine.

The engine is rules, not a model, so these tests pin the rules: boundary
comparisons, missing data, ranking determinism, gap reporting, what-if
semantics, privacy and the fairness assertion. They run against the throwaway
``amypo_test`` schema seeded with a small, fully controlled dataset so every
expected score is hand-computable.
"""

from __future__ import annotations

import json

import pytest

# --------------------------------------------------------------------------
# Seeding helpers
# --------------------------------------------------------------------------

_NOW = "2026-01-01T00:00:00+00:00"


def _seed(
    *,
    company_name: str = "TestCo",
    min_cgpa: float = 7.0,
    max_backlogs: int = 0,
    min_attendance_pct: float = 75.0,
    min_project_count: int = 1,
    min_communication: float = 3.0,
    departments: list[str] | None = None,
    weights: dict[str, float] | None = None,
    requirements: list[tuple[str, int, float, bool]] | None = None,
):
    """Create one company, one role and its requirements; return the role row."""
    from app.db import execute, query_one

    execute(
        "INSERT INTO companies (name, sector, tier, website, description, updated_at) "
        "VALUES (?, 'technology', 'A', NULL, NULL, ?)",
        (company_name, _NOW),
    )
    company = query_one(
        "SELECT company_id FROM companies WHERE name = ?", (company_name,)
    )
    departments_json = json.dumps(departments or ["CSE", "ECE"])
    weights_json = json.dumps(
        weights
        or {
            "skill_match": 0.40,
            "project_relevance": 0.20,
            "performance_trend": 0.15,
            "coding": 0.15,
            "communication": 0.10,
        }
    )
    execute(
        """
        INSERT INTO company_roles
            (company_id, title, location, package_lpa, min_cgpa, max_backlogs,
             min_attendance_pct, min_project_count, min_communication,
             allowed_departments, weights, updated_at)
        VALUES (?, 'Engineer', 'Pune', 8.0, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company["company_id"], min_cgpa, max_backlogs, min_attendance_pct,
            min_project_count, min_communication, departments_json, weights_json, _NOW,
        ),
    )
    role = query_one(
        "SELECT role_id FROM company_roles r JOIN companies c "
        "ON c.company_id = r.company_id WHERE c.name = ?",
        (company_name,),
    )

    all_skills = [("python", "Python"), ("sql", "SQL"), ("ml", "Machine Learning")]
    for skill_id, name in all_skills:
        execute(
            "INSERT INTO skills (skill_id, name, category, description) "
            "VALUES (?, ?, 'language', NULL) "
            "ON DUPLICATE KEY UPDATE name = VALUES(name)",
            (skill_id, name),
        )
    for skill_id, min_level, importance, is_required in requirements or [
        ("python", 3, 1.0, True),
        ("sql", 2, 0.5, True),
        ("ml", 2, 0.5, False),
    ]:
        execute(
            "INSERT INTO role_requirements (role_id, skill_id, min_level, importance, is_required) "
            "VALUES (?, ?, ?, ?, ?)",
            (role["role_id"], skill_id, min_level, importance, 1 if is_required else 0),
        )
    return query_one(
        "SELECT * FROM company_roles r JOIN companies c "
        "ON c.company_id = r.company_id WHERE c.name = ?",
        (company_name,),
    )


def _student(
    student_id: str = "T001",
    name: str = "Test Student",
    department: str = "CSE",
    cgpa: float = 8.0,
    backlogs: int = 0,
    attendance_pct: float = 85.0,
    communication_score: float = 4.0,
    project_count: int = 2,
    *,
    skills: dict[str, int] | None = None,
):
    from app.db import execute

    execute(
        """
        INSERT INTO students
            (student_id, name, department, year, cgpa, backlogs, attendance_pct,
             communication_score, project_count, email, updated_at)
        VALUES (?, ?, ?, 3, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (student_id, name, department, cgpa, backlogs, attendance_pct,
         communication_score, project_count, _NOW),
    )
    provided = skills if skills is not None else {"python": 3, "sql": 2, "ml": 2}
    for skill_id, level in provided.items():
        execute(
            "INSERT INTO student_skills (student_id, skill_id, level, evidence_source, updated_at) "
            "VALUES (?, ?, ?, 'module', ?)",
            (student_id, skill_id, level, _NOW),
        )
    execute(
        "INSERT INTO courses (course_id, title, department, credits, semester, updated_at) "
        "VALUES ('C1', 'Course One', 'CSE', 3, 1, ?) "
        "ON DUPLICATE KEY UPDATE title = VALUES(title)",
        (_NOW,),
    )
    execute(
        "INSERT INTO enrollments (student_id, course_id, semester, score, grade, "
        "project_grade, coding_score, updated_at) "
        "VALUES (?, 'C1', 1, 70, 'B', 80, 60, ?)",
        (student_id, _NOW),
    )
    return student_id


@pytest.fixture()
def engine(temp_db):
    from app.placement.engine import PlacementEngine

    return PlacementEngine()


# --------------------------------------------------------------------------
# Eligibility: boundaries and missing data
# --------------------------------------------------------------------------


def test_eligible_when_all_criteria_met(engine) -> None:
    _seed()
    _student("T001")
    results = engine.eligibility(student_id="T001")
    by_role = {(r.company, r.role): r for r in results}
    result = by_role[("TestCo", "Engineer")]
    assert result.eligible is True
    assert result.failing == []
    assert result.suitability is not None and result.suitability > 0


def test_cgpa_exactly_at_threshold_passes(engine) -> None:
    _seed(min_cgpa=8.0)
    _student("T001", cgpa=8.0)  # exactly the floor: not below it
    result = [
        r for r in engine.eligibility(student_id="T001") if r.company == "TestCo"
    ][0]
    assert result.eligible is True
    cgpa = [c for c in result.criteria if c.name == "cgpa"][0]
    assert cgpa.passed is True
    assert cgpa.actual == 8.0


def test_cgpa_just_below_threshold_fails(engine) -> None:
    _seed(min_cgpa=8.01)
    _student("T001", cgpa=8.0)
    result = [
        r for r in engine.eligibility(student_id="T001") if r.company == "TestCo"
    ][0]
    assert result.eligible is False
    assert "cgpa" in result.failing


def test_backlogs_ceiling_is_inclusive(engine) -> None:
    _seed(max_backlogs=1)
    _student("T001", backlogs=1)
    result = [
        r for r in engine.eligibility(student_id="T001") if r.company == "TestCo"
    ][0]
    assert result.eligible is True
    _student("T002", backlogs=2)
    result = [
        r for r in engine.eligibility(student_id="T002") if r.company == "TestCo"
    ][0]
    assert result.eligible is False
    assert "backlogs" in result.failing


def test_department_not_listed_is_blocking(engine) -> None:
    _seed(departments=["CSE"])
    _student("T001", department="Mechanical")
    result = [
        r for r in engine.eligibility(student_id="T001") if r.company == "TestCo"
    ][0]
    assert result.eligible is False
    assert "department" in result.failing


def test_preferred_skill_shortfall_is_not_blocking(engine) -> None:
    _seed(requirements=[("python", 3, 1.0, True), ("ml", 4, 0.5, False)])
    _student("T001", skills={"python": 3, "sql": 2, "ml": 0})
    result = [
        r for r in engine.eligibility(student_id="T001") if r.company == "TestCo"
    ][0]
    assert result.eligible is True  # preferred gaps never block
    ml = [c for c in result.criteria if c.name == "skill:ml"][0]
    assert ml.passed is False


def test_required_skill_shortfall_is_blocking(engine) -> None:
    _seed(requirements=[("python", 4, 1.0, True)])
    _student("T001", skills={"python": 3})
    result = [
        r for r in engine.eligibility(student_id="T001") if r.company == "TestCo"
    ][0]
    assert result.eligible is False
    assert "skill:python" in result.failing


def test_missing_skill_record_counts_as_level_zero(engine) -> None:
    _seed(requirements=[("python", 2, 1.0, True)])
    _student("T001", skills={})  # never took python
    result = [
        r for r in engine.eligibility(student_id="T001") if r.company == "TestCo"
    ][0]
    assert result.eligible is False
    python = [c for c in result.criteria if c.name == "skill:python"][0]
    assert python.actual == "level 0"


def test_unknown_student_yields_no_results(engine) -> None:
    _seed()
    assert engine.eligibility(student_id="NOPE") == []


def test_cohort_eligibility_covers_every_student(engine) -> None:
    _seed()
    _student("T001")
    _student("T002", cgpa=5.0)
    results = engine.eligibility(role_id=1, department=None) if False else engine.match(company="TestCo", role="Engineer")
    assert results is not None
    eligible_ids = [c.student_id for c in results.candidates]
    assert eligible_ids == ["T001"]  # T002 fails the CGPA floor


# --------------------------------------------------------------------------
# Ranking: suitability and determinism
# --------------------------------------------------------------------------


def test_ranking_is_by_suitability_then_student_id(engine) -> None:
    _seed()
    # Same eligibility, deliberately different profile strengths.
    _student("T050", name="Strong", skills={"python": 4, "sql": 4, "ml": 4},
             cgpa=9.0, project_count=3, communication_score=4.5)
    _student("T010", name="Weaker", skills={"python": 3, "sql": 2, "ml": 2},
             cgpa=7.5, project_count=1, communication_score=3.0)
    match = engine.match(company="TestCo", role="Engineer", top_n=5)
    ids = [c.student_id for c in match.candidates]
    assert ids == ["T050", "T010"]
    scores = [c.suitability for c in match.candidates]
    assert scores[0] > scores[1]


def test_ranking_is_deterministic_across_runs(engine) -> None:
    _seed()
    for i in range(6):
        _student(f"T{i:03d}", name=f"Student {i}", cgpa=7.0 + i * 0.1)
    orderings = []
    for _ in range(3):
        match = engine.match(company="TestCo", role="Engineer", top_n=10)
        orderings.append([(c.student_id, c.suitability) for c in match.candidates])
    assert orderings[0] == orderings[1] == orderings[2]
    # Equal profiles must tie-break by student_id, not by query order.
    match = engine.match(company="TestCo", role="Engineer", top_n=10)
    eligible_ids = [c.student_id for c in match.candidates]
    assert eligible_ids == sorted(eligible_ids)


def test_weights_are_renormalized_from_the_role(engine) -> None:
    from app.placement.suitability import load_weights

    _seed(weights={"skill_match": 2.0, "project_relevance": 1.0,
                   "performance_trend": 1.0, "coding": 0.0, "communication": 0.0})
    _student("T001")
    role = engine.resolve_role(company="TestCo", role="Engineer")
    weights = load_weights(role)
    total = sum(weights.values())
    assert total == pytest.approx(1.0)
    assert weights["skill_match"] == pytest.approx(0.5)
    assert weights["project_relevance"] == pytest.approx(0.25)
    assert weights["coding"] == 0.0


def test_suitability_is_between_0_and_100(engine) -> None:
    _seed()
    _student("T001")
    result = [
        r for r in engine.eligibility(student_id="T001") if r.company == "TestCo"
    ][0]
    assert 0.0 <= result.suitability <= 100.0


# --------------------------------------------------------------------------
# Closest misses
# --------------------------------------------------------------------------


def test_closest_miss_fails_exactly_one_criterion(engine) -> None:
    _seed(min_cgpa=9.0)
    _student("T001", cgpa=8.0)  # only CGPA fails
    _student("T002", cgpa=5.0, attendance_pct=50, project_count=0,
             communication_score=1.0, backlogs=3)  # fails many
    match = engine.match(company="TestCo", role="Engineer", top_n=5)
    assert match.candidates == []
    miss_ids = [m.student_id for m in match.closest_misses]
    assert miss_ids == ["T001"]
    assert len(match.closest_misses[0].failing) == 1


# --------------------------------------------------------------------------
# Skill gaps and learning paths
# --------------------------------------------------------------------------


def test_skill_gap_reports_blocking_then_weak(engine) -> None:
    _seed(requirements=[("python", 4, 1.0, True), ("sql", 2, 0.5, True),
                        ("ml", 3, 0.5, False)])
    _student("T001", skills={"python": 2, "sql": 2, "ml": 0})
    report = engine.skill_gap("T001", company="TestCo", role="Engineer")
    severities = [g.severity for g in report.gaps if g.severity != "ok"]
    assert severities.count("blocking") >= 1  # python is short and required
    assert "weak" in severities
    blocking = [g for g in report.gaps if g.severity == "blocking"]
    assert blocking[0].skill.lower() == "python"
    assert blocking[0].required_level == 4 and blocking[0].current_level == 2


def test_learning_path_cites_a_real_record(engine) -> None:
    _seed(requirements=[("python", 4, 1.0, True)])
    _student("T001", skills={"python": 1})
    report = engine.skill_gap("T001", company="TestCo", role="Engineer")
    assert report.learning_path, "a blocking gap must produce a step"
    step = report.learning_path[0]
    assert step.record_id  # every suggestion must be resolvable
    assert step.effort_weeks >= 1.0
    # The cited record is a skills row or a public catalogue chunk.
    assert step.record_id.startswith(("db:skills:", "doc:"))


def test_no_gaps_when_all_levels_met(engine) -> None:
    _seed()
    _student("T001", skills={"python": 3, "sql": 2, "ml": 3})
    report = engine.skill_gap("T001", company="TestCo", role="Engineer")
    assert all(g.severity == "ok" for g in report.gaps)
    assert report.learning_path == []


# --------------------------------------------------------------------------
# What-if
# --------------------------------------------------------------------------


def test_what_if_cgpa_boost_opens_the_role(engine) -> None:
    _seed(min_cgpa=9.0)
    _student("T001", cgpa=8.0)
    from app.core.schemas import WhatIfRequest

    result = engine.what_if(WhatIfRequest(student_id="T001", cgpa=9.5))
    assert result.baseline_eligible == []
    key = "TestCo Engineer"
    assert key in result.opened_up
    assert key in result.projected_eligible
    per_role = {r["role"]: r for r in result.per_role}[key]
    assert per_role["was_eligible"] is False
    assert per_role["now_eligible"] is True


def test_what_if_skill_boost_opens_the_role(engine) -> None:
    _seed(requirements=[("python", 4, 1.0, True)])
    _student("T001", skills={"python": 3})
    from app.core.schemas import WhatIfRequest

    result = engine.what_if(WhatIfRequest(student_id="T001", skill_levels={"python": 4}))
    assert "TestCo Engineer" in result.opened_up


def test_what_if_can_lose_eligibility(engine) -> None:
    _seed(min_cgpa=7.0, max_backlogs=1)
    _student("T001", cgpa=8.0, backlogs=0)
    from app.core.schemas import WhatIfRequest

    result = engine.what_if(WhatIfRequest(student_id="T001", backlogs=2))
    assert result.lost == ["TestCo Engineer"]


def test_what_if_does_not_persist(engine) -> None:
    from app.db import query_one

    _seed(min_cgpa=9.0)
    _student("T001", cgpa=8.0)
    from app.core.schemas import WhatIfRequest

    engine.what_if(WhatIfRequest(student_id="T001", cgpa=9.5))
    row = query_one("SELECT cgpa FROM students WHERE student_id = ?", ("T001",))
    assert row["cgpa"] == 8.0  # the override never touched the record


# --------------------------------------------------------------------------
# Privacy, audit and fairness
# --------------------------------------------------------------------------


def test_student_cannot_view_another_students_eligibility(api_client, temp_db) -> None:
    _seed()
    _student("T001")
    _student("T002")
    # A student session: the student id comes from the token, so asking for
    # T002 is refused rather than silently rewritten to T001.
    student = api_client("student", student_id="T001")
    resp = student.get(
        "/api/v1/placement/eligibility", params={"student_id": "T002"}
    )
    assert resp.status_code == 403


def test_student_can_view_own_eligibility(api_client, temp_db) -> None:
    _seed()
    _student("T001")
    student = api_client("student", student_id="T001")
    resp = student.get("/api/v1/placement/eligibility", params={"student_id": "T001"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["student_id"] == "T001"


def test_cohort_endpoint_denied_for_students(api_client, temp_db) -> None:
    _seed()
    student = api_client("student", student_id="T001")
    resp = student.get("/api/v1/placement/eligibility", params={"company": "TestCo"})
    assert resp.status_code == 403


def test_cohort_query_is_audited(client, temp_db) -> None:
    from app.db import query

    _seed()
    _student("T001")
    resp = client.get(
        "/api/v1/placement/eligibility", params={"company": "TestCo"}
    )
    assert resp.status_code == 200, resp.text
    rows = query("SELECT kind, company, result_count FROM cohort_queries ORDER BY id DESC")
    assert rows, "a cohort query must be logged"
    assert rows[0]["kind"] == "eligibility"
    assert rows[0]["company"] == "TestCo"
    assert rows[0]["result_count"] == len(resp.json()["results"])


def test_ask_cohort_match_is_audited(client, temp_db) -> None:
    from app.db import query

    _seed()
    _student("T001")
    resp = client.post(
        "/api/v1/ask",
        json={"question": "Who is eligible for TestCo Engineer?", "user_id": None,
              "role": "staff"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert not body["abstained"]
    assert "T001" in body["answer"]
    rows = query("SELECT kind FROM cohort_queries ORDER BY id DESC")
    assert rows[0]["kind"] == "ask_match"


def test_ask_student_cohort_falls_back_without_other_names(api_client, temp_db) -> None:
    _seed()
    _student("T001")
    _student("T002")
    # A student session: the cohort answer is a staff capability, so the
    # pipeline must fall back without naming another student.
    student = api_client("student", student_id="T002")
    resp = student.post(
        "/api/v1/ask", json={"question": "Who is eligible for TestCo Engineer?"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "T001" not in body["answer"]


def test_protected_attributes_are_never_features() -> None:
    from app.placement.engine import SUITABILITY_FEATURES
    from app.placement.fairness import PROTECTED_ATTRIBUTES

    assert PROTECTED_ATTRIBUTES.isdisjoint(SUITABILITY_FEATURES)


def test_fairness_guard_rejects_a_protected_feature() -> None:
    from app.placement import fairness

    with pytest.raises(ValueError):
        fairness.assert_no_protected_attributes(("gender",))
    fairness.assert_no_protected_attributes(("skill_match", "cgpa"))  # fine


def test_sources_carry_record_ids(client, temp_db) -> None:
    _seed()
    _student("T001")
    results = engine_factory().eligibility(student_id="T001")
    result = results[0]
    record_ids = {s.record_id for s in result.sources}
    assert "db:students:T001" in record_ids
    assert any(rid.startswith("db:company_roles:") for rid in record_ids)


def engine_factory():
    from app.placement.engine import PlacementEngine

    return PlacementEngine()
