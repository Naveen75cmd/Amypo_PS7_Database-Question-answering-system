"""End-to-end smoke test against a running AMYPO stack.

Exercises the product the way a user does -- sign in, ask, get refused, open
the placement tools, the admin surface and the audit log -- over HTTP, with the
three seeded demo roles. It asserts behaviour, not just status codes: a student
must be denied another student's record, staff must see the placement internals
a student cannot, an unanswerable question must abstain rather than invent, and
a denied action must land in the audit log.

Usage:
    python scripts/e2e_smoke.py                       # http://127.0.0.1:8000
    python scripts/e2e_smoke.py --base http://host:8000 --skip-eval
"""

from __future__ import annotations

import argparse
import json
import sys
import time

BASE_DEFAULT = "http://127.0.0.1:8000/api/v1"
PASSWORD = "amypo-demo-2026"
DEMO = {
    "admin": ("admin", "admin"),
    "staff": ("staff.cse", "staff"),
    "student": ("s102", "student"),
}
# Questions verified to be answerable in the extractive configuration. The
# wording matters: this product abstains rather than guess, so a vague phrasing
# ("what is the attendance policy?") legitimately comes back as an abstention.
Q_GROUNDED = "What is the minimum attendance required for exams?"
Q_ABSTAIN = "What is the Wi-Fi password for the hostel?"
Q_STAFF_DOC = "What are the internal notes for the placement officer?"
Q_ELIGIBLE = "Am I eligible for the Zoho SDE role?"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE_DEFAULT)
    parser.add_argument("--skip-eval", action="store_true", help="skip POST /eval/run")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    import httpx

    client = httpx.Client(base_url=base, timeout=180.0, follow_redirects=False)

    # --- health and open endpoints -----------------------------------------
    health = client.get("/health")
    body = health.json() if health.status_code == 200 else {}
    components = body.get("components", {})
    check("health 200", health.status_code == 200, str(health.status_code))
    check(
        "health reports db/index/llm/router",
        {"db", "index", "llm", "router"} <= set(components),
        ",".join(sorted(components)),
    )
    check(
        "corpus is indexed",
        "chunks" in components.get("index", {}).get("detail", ""),
        components.get("index", {}).get("detail", "")[:70],
    )
    check("resource-status open", client.get("/resource-status").status_code == 200)

    # --- auth: three roles, and the generic failure ------------------------
    tokens: dict[str, str] = {}
    for role, (username, expected) in DEMO.items():
        resp = client.post("/auth/login", json={"username": username, "password": PASSWORD})
        ok = resp.status_code == 200
        token = resp.json().get("access_token") if ok else None
        if token:
            tokens[role] = token
        check(f"login {role} ({username})", ok, str(resp.status_code))
        me = httpx.get(
            f"{base}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=30.0
        ) if token else None
        role_ok = me is not None and me.status_code == 200 and me.json().get("role") == expected
        check(f"/auth/me role = {expected}", role_ok, str(me.status_code) if me else "no token")

    bad = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    check(
        "wrong password refused with a generic message",
        bad.status_code == 401 and "incorrect" in bad.text.lower(),
        f"{bad.status_code} {bad.text[:60]}",
    )
    # A separate client, so the login cookies above cannot authenticate this.
    check("no token -> 401", httpx.get(f"{base}/auth/me", timeout=30.0).status_code == 401)
    check(
        "forged token -> 401",
        httpx.get(
            f"{base}/auth/me",
            headers={"Authorization": "Bearer not.a.jwt"},
            timeout=30.0,
        ).status_code
        == 401,
    )

    def post(role: str, path: str, payload: dict) -> httpx.Response:
        return client.post(
            path, json=payload, headers={"Authorization": f"Bearer {tokens[role]}"}
        )

    def get(role: str, path: str, **kwargs) -> httpx.Response:
        return client.get(path, headers={"Authorization": f"Bearer {tokens[role]}"}, **kwargs)

    # --- chat: grounded answer, citation, trace ---------------------------
    ask = post("student", "/ask", {"question": Q_GROUNDED})
    answer = ask.json() if ask.status_code == 200 else {}
    check("ask 200 (student)", ask.status_code == 200, str(ask.status_code))
    check(
        "answer is grounded and cited",
        bool(answer.get("answer")) and bool(answer.get("sources")) and not answer.get("abstained"),
        f"{len(answer.get('sources') or [])} sources",
    )
    check(
        "answer carries the policy number",
        "75" in (answer.get("answer") or ""),
        (answer.get("answer") or "")[:70],
    )
    trace = get("student", f"/ask/trace/{answer.get('trace_id', 'missing')}")
    trace_body = trace.json() if trace.status_code == 200 else {}
    check("trace retrievable", trace.status_code == 200, str(trace.status_code))
    check(
        "trace shows the decision path",
        bool(trace_body.get("steps")) and bool(trace_body.get("retrieval")),
        f"{len(trace_body.get('steps') or [])} steps",
    )

    # --- abstention on an unanswerable question --------------------------
    unans = post("student", "/ask", {"question": Q_ABSTAIN})
    unans_body = unans.json() if unans.status_code == 200 else {}
    check(
        "unanswerable question abstains",
        unans.status_code == 200 and unans_body.get("abstained") is True,
        f"abstained={unans_body.get('abstained')}",
    )
    check(
        "abstention names the closest records",
        bool(unans_body.get("closest_records")),
        f"{len(unans_body.get('closest_records') or [])} records",
    )
    check(
        "abstention offers a clarifying question",
        bool(unans_body.get("clarifying_question")),
        (unans_body.get("clarifying_question") or "")[:60],
    )

    # --- access control ---------------------------------------------------
    denied = post("student", "/ask", {"question": "Show me the grades of student S101"})
    denied_body = denied.json() if denied.status_code == 200 else {}
    check(
        "student cannot read another student's record",
        denied.status_code == 200 and denied_body.get("abstained") is True,
        f"abstained={denied_body.get('abstained')}",
    )
    own = post("student", "/ask", {"question": "What is my CGPA?"})
    own_body = own.json() if own.status_code == 200 else {}
    check(
        "student can read their own record",
        own.status_code == 200 and not own_body.get("abstained"),
        (own_body.get("answer") or "")[:60],
    )

    staff_doc = post("staff", "/ask", {"question": Q_STAFF_DOC})
    staff_body = staff_doc.json() if staff_doc.status_code == 200 else {}
    staff_ids = [s.get("record_id", "") for s in (staff_body.get("sources") or [])]
    student_doc = post("student", "/ask", {"question": Q_STAFF_DOC})
    student_body = student_doc.json() if student_doc.status_code == 200 else {}
    student_ids = [s.get("record_id", "") for s in (student_body.get("sources") or [])]
    check(
        "staff receives the staff-only document",
        staff_doc.status_code == 200
        and any(rid.startswith("doc:placement-internals") for rid in staff_ids),
        ", ".join(staff_ids[:3]),
    )
    check(
        "student receives no staff-only document",
        not any(rid.startswith("doc:placement-internals") for rid in student_ids),
        f"abstained={student_body.get('abstained')} sources={len(student_ids)}",
    )

    for path in ("/admin/users", "/admin/audit"):
        check(f"student blocked from {path}", get("student", path).status_code == 403, str(get("student", path).status_code))
        check(f"staff blocked from {path}", get("staff", path).status_code == 403, str(get("staff", path).status_code))
    check("admin may read /admin/users", get("admin", "/admin/users").status_code == 200)
    check("admin may read /admin/audit", get("admin", "/admin/audit").status_code == 200)
    # The staff dashboard is read-only, so staff legitimately see aggregate
    # metrics; students do not.
    check("staff may read /metrics", get("staff", "/metrics").status_code == 200)
    check("student blocked from /metrics", get("student", "/metrics").status_code == 403)

    # --- placement --------------------------------------------------------
    student_id = "S102"
    eligibility = get("student", "/placement/eligibility")
    check("student eligibility", eligibility.status_code == 200, str(eligibility.status_code))
    gap = get("student", f"/placement/skill-gap/{student_id}")
    check("student skill gap", gap.status_code == 200, str(gap.status_code))
    what_if = post("student", "/placement/what-if", {"student_id": student_id, "target_role": "Zoho SDE"})
    check("student what-if", what_if.status_code == 200, str(what_if.status_code))
    cohort = get("staff", "/placement/cohort-queries")
    check("staff cohort query", cohort.status_code == 200, str(cohort.status_code))
    match = post("staff", "/placement/match", {"student_id": student_id})
    check("staff match", match.status_code == 200, str(match.status_code))
    pdf = get("student", f"/placement/eligibility/{student_id}/report.pdf")
    check(
        "eligibility report is a PDF",
        pdf.status_code == 200 and pdf.content[:4] == b"%PDF",
        f"{pdf.status_code} {len(pdf.content)} bytes",
    )
    chat_elig = post("student", "/ask", {"question": Q_ELIGIBLE})
    chat_body = chat_elig.json() if chat_elig.status_code == 200 else {}
    check(
        "chat answers a specific eligibility question from records",
        chat_elig.status_code == 200
        and not chat_body.get("abstained")
        and "Zoho" in (chat_body.get("answer") or ""),
        (chat_body.get("answer") or "")[:70],
    )

    # --- admin surfaces ---------------------------------------------------
    users = get("admin", "/admin/users").json()
    user_rows = users if isinstance(users, list) else (users.get("users") or users.get("items") or [])
    usernames = {u.get("username") for u in user_rows if isinstance(u, dict)}
    check(
        "seeded accounts exist",
        {"admin", "staff.cse", "s102"} <= usernames,
        f"{len(user_rows)} accounts",
    )
    audit = get("admin", "/admin/audit").json()
    entries = audit.get("entries") if isinstance(audit, dict) else audit
    check("audit log has entries", bool(entries), f"{len(entries or [])} entries")
    audit_text = json.dumps(audit).lower()
    check(
        "the refusal was audited",
        "denied" in audit_text or "forbidden" in audit_text or "403" in audit_text,
        audit_text[:60],
    )

    # --- evaluation (the artefact the judges read) ------------------------
    if not args.skip_eval:
        started = time.perf_counter()
        run = post("admin", "/eval/run", {"limit": 6, "write_report": False})
        elapsed = time.perf_counter() - started
        run_body = run.json() if run.status_code == 200 else {}
        check("eval/run 200 (admin)", run.status_code == 200, f"{run.status_code} {elapsed:.1f}s")
        check(
            "eval returns metrics",
            "accuracy" in run_body and "routing_agreement" in run_body,
            ",".join(sorted(run_body)[:6]),
        )
        check("eval blocked for staff", post("staff", "/eval/run", {"limit": 2}).status_code == 403)

    # --- report -----------------------------------------------------------
    width = max(len(name) for name, _, _ in results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\nE2E smoke test against {base}\n" + "-" * (width + 44))
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    print("-" * (width + 44))
    print(f"{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
