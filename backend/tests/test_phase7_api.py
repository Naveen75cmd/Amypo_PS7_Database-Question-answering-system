"""The Phase 7 surfaces: query history and the knowledge index listing.

History is an access-control surface (students see only their own queries);
the document listing is metadata the Knowledge page renders.
"""

from __future__ import annotations


def test_history_returns_asked_questions_for_staff(client, temp_db) -> None:
    client.post("/api/v1/ask", json={"question": "What is the attendance policy?"})
    resp = client.get("/api/v1/ask/history", params={"limit": 10})
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows, "an answered question must appear in the history"
    assert rows[0]["question"] == "What is the attendance policy?"
    assert rows[0]["request_id"]


def test_history_is_scoped_for_students(api_client, temp_db) -> None:
    s102 = api_client("student", student_id="S102")
    s103 = api_client("student", student_id="S103")
    s102.post("/api/v1/ask", json={"question": "What is my CGPA?"})
    s103.post("/api/v1/ask", json={"question": "Who is eligible for Zoho SDE?"})
    resp = s102.get("/api/v1/ask/history", params={"limit": 20})
    assert resp.status_code == 200, resp.text
    users = {row["user_id"] for row in resp.json()}
    assert users <= {"S102"}, "a student must see only their own queries"
    assert users, "the student's own question must still be there"


def test_history_limit_is_respected(client, temp_db) -> None:
    for i in range(3):
        client.post("/api/v1/ask", json={"question": f"Question {i}?"})
    resp = client.get("/api/v1/ask/history", params={"limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()) <= 2


def test_documents_listing_reports_chunk_counts(client, temp_db) -> None:
    from app.ingest.pipeline import ingest_all
    from app.core.settings import settings

    ingest_all(path=settings.raw_dir, force=False)
    resp = client.get("/api/v1/ingest/documents")
    assert resp.status_code == 200, resp.text
    docs = resp.json()
    assert docs, "the seeded corpus must produce documents"
    sample = docs[0]
    assert {"doc_id", "title", "chunk_count", "access_scope"} <= set(sample)
    assert all(d["chunk_count"] >= 0 for d in docs)
