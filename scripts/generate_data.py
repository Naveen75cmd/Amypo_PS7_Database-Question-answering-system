"""Generate the synthetic AMYPO-style dataset.

Deterministic: same seed -> byte-identical output. Writes structured CSVs to
``data/synthetic/``, documents to ``data/raw/`` and the benchmark to
``data/eval/benchmark.jsonl``.

The benchmark is built by ``app.eval.benchmark_spec`` *after* the documents are
written, so its gold source ids are resolved against the real chunker. That is
why generation has two stages: data first, then labels derived from the data.

Usage:
    python scripts/generate_data.py [--seed 20260203] [--students 300]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.dataspec import (  # noqa: E402
    COMPANIES,
    COURSES,
    DAY_NAMES,
    DEPARTMENTS,
    FACULTY_NAMES,
    INDIAN_FIRST_NAMES,
    INDIAN_LAST_NAMES,
    ROOM_PREFIXES,
    SKILLS,
    TIME_SLOTS,
)

RAW = PROJECT_ROOT / "data" / "raw"
SYNTHETIC = PROJECT_ROOT / "data" / "synthetic"
EVAL = PROJECT_ROOT / "data" / "eval"

AS_OF = date(2026, 9, 1)


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def iso(d: date) -> str:
    return d.isoformat()


# --------------------------------------------------------------------------
# generators
# --------------------------------------------------------------------------


def gen_students(rng: random.Random, count: int) -> tuple[list[list], list[dict]]:
    rows: list[list] = []
    records: list[dict] = []
    used: set[str] = set()
    for i in range(1, count + 1):
        student_id = f"S{100 + i}"
        while True:
            name = f"{rng.choice(INDIAN_FIRST_NAMES)} {rng.choice(INDIAN_LAST_NAMES)}"
            if name not in used:
                used.add(name)
                break
        dept = rng.choice(DEPARTMENTS)
        cgpa = round(min(10.0, max(4.5, rng.gauss(7.1, 0.85))), 2)
        year = rng.choice([2, 3, 3, 4, 4])
        attendance = round(min(100.0, max(45.0, rng.gauss(78.0, 12.0))), 1)
        backlogs = 0 if cgpa > 6.5 else rng.choices([0, 1, 2, 3], [0.5, 0.3, 0.15, 0.05])[0]
        communication = round(min(5.0, max(1.0, rng.gauss(3.2, 0.9))), 1)
        project_count = rng.choices([0, 1, 2, 3, 4], [0.12, 0.28, 0.3, 0.2, 0.1])[0]
        email = f"{name.split()[0].lower()}.{student_id.lower()}@amypo.edu.in"
        rows.append([
            student_id, name, dept, year, cgpa, backlogs, attendance,
            communication, project_count, email, iso(AS_OF),
        ])
        records.append({
            "student_id": student_id, "name": name, "department": dept, "year": year,
            "cgpa": cgpa, "backlogs": backlogs, "attendance_pct": attendance,
            "communication_score": communication, "project_count": project_count,
        })
    return rows, records


def gen_courses() -> list[list]:
    return [
        [cid, title, dept, credits, sem, iso(AS_OF)]
        for cid, title, dept, credits, sem in COURSES
    ]


def gen_enrollments(
    rng: random.Random, students: list[dict]
) -> tuple[list[list], list[list], list[list], dict[str, list[tuple[str, float]]]]:
    enroll_rows: list[list] = []
    grade_rows: list[list] = []
    att_rows: list[list] = []
    per_student: dict[str, list[tuple[str, float]]] = {}

    courses_by_dept: dict[str, list[tuple]] = {}
    for c in COURSES:
        courses_by_dept.setdefault(c[2], []).append(c)
    common = [c for c in COURSES if c[2] == "Humanities"]

    for st in students:
        sid = st["student_id"]
        pool = list(courses_by_dept.get(st["department"], [])) + common
        rng.shuffle(pool)
        chosen = pool[: rng.randint(5, 7)]
        results: list[tuple[str, float]] = []
        for cid, title, dept, credits, sem in chosen:
            base = (st["cgpa"] / 10.0) * 100
            score = round(min(100.0, max(22.0, rng.gauss(base, 9.0))), 1)
            project_grade = round(min(100.0, max(30.0, rng.gauss(base + 2, 10.0))), 1)
            coding = round(min(100.0, max(15.0, rng.gauss(base - 3, 13.0))), 1)
            grade = (
                "O" if score >= 90 else "A+" if score >= 80 else "A" if score >= 70
                else "B+" if score >= 60 else "B" if score >= 50 else "C"
            )
            enroll_rows.append([
                sid, cid, sem, score, grade, project_grade, coding, iso(AS_OF),
            ])
            for assessment, value, weight in (
                ("midterm", round(score * rng.uniform(0.9, 1.05), 1), 0.4),
                ("final", score, 0.6),
            ):
                grade_rows.append([
                    sid, cid, assessment, min(100.0, value), 100.0, weight, iso(AS_OF),
                ])
            held = rng.randint(28, 44)
            pct = min(100.0, max(35.0, rng.gauss(st["attendance_pct"], 7.0)))
            attended = round(held * pct / 100)
            att_rows.append([
                sid, cid, attended, held, round(attended / held * 100, 1), iso(AS_OF),
            ])
            results.append((cid, score))
        per_student[sid] = results
    return enroll_rows, grade_rows, att_rows, per_student


def gen_schedules() -> list[list]:
    rows: list[list] = []
    for idx, (cid, title, dept, credits, sem) in enumerate(COURSES):
        day = DAY_NAMES[idx % len(DAY_NAMES)]
        start, end = TIME_SLOTS[idx % len(TIME_SLOTS)]
        room = f"{ROOM_PREFIXES[idx % len(ROOM_PREFIXES)]}-{101 + idx}"
        faculty = FACULTY_NAMES[idx % len(FACULTY_NAMES)]
        rows.append([cid, day, start, end, room, faculty, iso(AS_OF)])
    return rows


def gen_skills() -> list[list]:
    return [[sid, name, cat, f"{name} ({cat})"] for sid, name, cat, _ in SKILLS]


def gen_student_skills(
    rng: random.Random, students: list[dict], per_student: dict[str, list[tuple[str, float]]]
) -> list[list]:
    rows: list[list] = []
    for st in students:
        sid = st["student_id"]
        scores = per_student.get(sid, [])
        avg_score = sum(s for _, s in scores) / len(scores) if scores else 55.0
        n_skills = rng.randint(8, 14)
        chosen = rng.sample(SKILLS, n_skills)
        for skill_id, name, cat, difficulty in chosen:
            if cat == "soft":
                level = int(min(5, max(1, round(st["communication_score"]))))
                evidence_source, evidence_ref = "self", None
            elif cat in ("fundamentals", "ai") and difficulty >= 4:
                level = int(min(5, max(0, round((avg_score - 45) / 11))))
                evidence_source, evidence_ref = "module", scores[0][0] if scores else None
            else:
                level = int(min(5, max(0, round((avg_score - 50) / 10 + rng.uniform(-1, 1)))))
                evidence_source = rng.choice(["module", "project", "coding_test"])
                evidence_ref = rng.choice(scores)[0] if scores else None
            rows.append([
                sid, skill_id, level, evidence_source, evidence_ref, iso(AS_OF),
            ])
    return rows


def rng_city(company: str) -> str:
    mapping = {
        "Zoho": "Chennai", "TCS Digital": "Chennai", "Infosys": "Bengaluru",
        "Freshworks": "Chennai", "Wipro": "Coimbatore", "Cognizant": "Chennai",
        "Capgemini": "Pune", "Amazon": "Hyderabad", "Microsoft": "Hyderabad",
        "Zoho Analytics": "Chennai", "Fidelity Investments": "Chennai",
        "Bosch": "Coimbatore", "Tata Elxsi": "Thiruvananthapuram",
        "Rocket Learning": "Remote", "Verizon India": "Chennai",
    }
    return mapping.get(company, "Chennai")


def gen_companies() -> tuple[list[list], list[list], list[list]]:
    """Companies, roles and requirements.

    ``role_index`` is the 1-based position in global generation order. Roles are
    inserted in this same order, so the SQLite ``role_id`` matches it, which is
    what lets the benchmark label a role as ``db:company_roles:<n>``.
    """
    company_rows: list[list] = []
    role_rows: list[list] = []
    req_rows: list[list] = []
    role_index = 0
    for cidx, (name, sector, tier, roles) in enumerate(COMPANIES, start=1):
        company_rows.append([
            cidx, name, sector, tier, f"https://www.{name.split()[0].lower()}.com",
            f"{name} is a {sector.lower()} organisation hiring from AMYPO campuses.",
            iso(AS_OF),
        ])
        for rtitle, package, min_cgpa, max_backlogs, min_att, min_proj, min_comm, depts, reqs in roles:
            role_index += 1
            weights = {
                "skill_match": 0.40,
                "project_relevance": 0.20,
                "performance_trend": 0.15,
                "coding": 0.15,
                "communication": 0.10,
            }
            role_rows.append([
                cidx, rtitle, rng_city(name), package, min_cgpa, max_backlogs,
                min_att, min_proj, min_comm, json.dumps(depts), json.dumps(weights),
                iso(AS_OF),
            ])
            for skill_id, min_level, importance, is_required in reqs:
                req_rows.append([
                    role_index, skill_id, min_level, importance, 1 if is_required else 0,
                ])
    return company_rows, role_rows, req_rows


def gen_query_log(rng: random.Random, count: int = 200) -> list[dict]:
    templates = [
        "What is the minimum attendance for exams?",
        "What is my attendance in {course}?",
        "Am I eligible for {company}?",
        "What is my CGPA?",
        "How do I apply for a bonafide certificate?",
        "What is the fee refund policy?",
        "Can I attend the {company} drive with {backlogs} backlogs?",
        "What skills do I need for {company} {role}?",
        "When is the {course} exam?",
        "How many backlogs are allowed for placements?",
        "What is the package for {company}?",
        "Is there a dress code for interviews?",
        "How do I improve my chances for {company}?",
        "What is the library fine for an overdue book?",
        "Can I get a dream offer permit?",
        "What is the hostel curfew?",
        "How many credits do I need to graduate?",
        "What is the scholarship application deadline?",
        "Where is my hall ticket?",
        "What is the placement training attendance requirement?",
        "Compare Infosys and TCS eligibility for me.",
        "What is my attendance and CGPA together?",
        "Which companies can I apply for with a 7.2 CGPA?",
        "What is the maximum grade in a supplementary exam?",
        "How long is an internship?",
    ]
    course_ids = [c[0] for c in COURSES]
    company_names = [c[0] for c in COMPANIES]
    role_names = [r[0] for _, _, _, roles in COMPANIES for r in roles]
    out: list[dict] = []
    for i in range(count):
        t = rng.choice(templates)
        q = t.format(
            course=rng.choice(course_ids),
            company=rng.choice(company_names),
            role=rng.choice(role_names),
            backlogs=rng.choice([0, 1, 2, 3]),
        )
        out.append({"query_id": f"h{i + 1:03d}", "question": q})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260203)
    parser.add_argument("--students", type=int, default=300)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    RAW.mkdir(parents=True, exist_ok=True)
    SYNTHETIC.mkdir(parents=True, exist_ok=True)
    EVAL.mkdir(parents=True, exist_ok=True)

    student_rows, student_records = gen_students(rng, args.students)
    write_csv(
        SYNTHETIC / "students.csv",
        ["student_id", "name", "department", "year", "cgpa", "backlogs",
         "attendance_pct", "communication_score", "project_count", "email", "updated_at"],
        student_rows,
    )

    course_rows = gen_courses()
    write_csv(
        SYNTHETIC / "courses.csv",
        ["course_id", "title", "department", "credits", "semester", "updated_at"],
        course_rows,
    )

    enroll_rows, grade_rows, att_rows, per_student = gen_enrollments(rng, student_records)
    write_csv(
        SYNTHETIC / "enrollments.csv",
        ["student_id", "course_id", "semester", "score", "grade", "project_grade",
         "coding_score", "updated_at"],
        enroll_rows,
    )
    write_csv(
        SYNTHETIC / "grades.csv",
        ["student_id", "course_id", "assessment", "score", "max_score", "weight", "recorded_at"],
        grade_rows,
    )
    write_csv(
        SYNTHETIC / "attendance.csv",
        ["student_id", "course_id", "attended", "held", "percent", "as_of"],
        att_rows,
    )
    write_csv(
        SYNTHETIC / "schedules.csv",
        ["course_id", "day_of_week", "start_time", "end_time", "room", "faculty", "updated_at"],
        gen_schedules(),
    )
    write_csv(
        SYNTHETIC / "skills.csv",
        ["skill_id", "name", "category", "description"],
        gen_skills(),
    )
    skill_rows = gen_student_skills(rng, student_records, per_student)
    write_csv(
        SYNTHETIC / "student_skills.csv",
        ["student_id", "skill_id", "level", "evidence_source", "evidence_ref", "updated_at"],
        skill_rows,
    )

    company_rows, role_rows, req_rows = gen_companies()
    write_csv(
        SYNTHETIC / "companies.csv",
        ["company_id", "name", "sector", "tier", "website", "description", "updated_at"],
        company_rows,
    )
    write_csv(
        SYNTHETIC / "company_roles.csv",
        ["company_id", "title", "location", "package_lpa", "min_cgpa", "max_backlogs",
         "min_attendance_pct", "min_project_count", "min_communication",
         "allowed_departments", "weights", "updated_at"],
        role_rows,
    )
    write_csv(
        SYNTHETIC / "role_requirements.csv",
        ["role_index", "skill_id", "min_level", "importance", "is_required"],
        req_rows,
    )

    # Documents must exist before the benchmark, which resolves gold ids by
    # locating phrases inside the real chunks.
    from app.ingest.documents import DOCUMENTS  # noqa: E402

    for filename, title, body in DOCUMENTS:
        write_text(RAW / filename, body)

    history = gen_query_log(rng)
    with (EVAL / "query_history.jsonl").open("w", encoding="utf-8") as fh:
        for item in history:
            fh.write(json.dumps(item) + "\n")

    from app.eval.benchmark_spec import build_benchmark, write_benchmark  # noqa: E402

    benchmark_path = EVAL / "benchmark.jsonl"
    write_benchmark(benchmark_path, student_records)
    benchmark = build_benchmark(student_records)

    unresolved = [
        item["id"] for item in benchmark
        if item["answerable"] and not item["gold_sources"]
    ]
    if unresolved:
        print(f"ERROR: {len(unresolved)} answerable questions have no gold source: "
              f"{unresolved[:10]}", file=sys.stderr)
        return 1

    kinds: dict[str, int] = {}
    for item in benchmark:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    summary = {
        "seed": args.seed,
        "students": len(student_rows),
        "courses": len(course_rows),
        "enrollments": len(enroll_rows),
        "grades": len(grade_rows),
        "attendance_rows": len(att_rows),
        "skills": len(SKILLS),
        "student_skills": len(skill_rows),
        "companies": len(company_rows),
        "roles": len(role_rows),
        "role_requirements": len(req_rows),
        "documents": len(DOCUMENTS),
        "history_queries": len(history),
        "benchmark_total": len(benchmark),
        "benchmark_by_kind": kinds,
    }
    (SYNTHETIC / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"\nWrote documents to {RAW}")
    print(f"Wrote structured CSVs to {SYNTHETIC}")
    print(f"Wrote benchmark to {benchmark_path} (all gold ids resolved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
