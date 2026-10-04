"""Phase 2 definition of done: chunking and record-id stability.

Also asserts the ingestion pipeline is idempotent: re-running it leaves the
corpus byte-identical.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.settings import settings
from app.ingest.chunking import (
    chunk_document,
    count_tokens,
    db_record_id,
    split_sections,
    stable_record_id,
)

SAMPLE = """# Attendance Policy

## 1. Minimum requirement
Students must maintain a minimum of 75% attendance in each registered course to be
eligible to appear for the end-semester examination.

## 2. Condonation
Students with attendance between 65% and 75% may apply for condonation on medical
grounds.

## 3. Below 65%
Students below 65% attendance in a course are not permitted to write that course's
end-semester examination.
"""


def test_record_id_scheme() -> None:
    assert stable_record_id("attendance-policy", 0) == "doc:attendance-policy#0"
    assert stable_record_id("attendance-policy", 7) == "doc:attendance-policy#7"
    assert db_record_id("students", "S102") == "db:students:S102"
    assert db_record_id("company_roles", 3) == "db:company_roles:3"


def test_sections_split_on_headings() -> None:
    sections = split_sections(SAMPLE, default_title="Attendance Policy")
    titles = [s.title for s in sections]
    # The H1 is the document title; the three H2s are the sections.
    assert titles == ["1. Minimum requirement", "2. Condonation", "3. Below 65%"]
    assert "75% attendance" in sections[0].body


def test_chunk_ids_are_stable_and_sequential() -> None:
    first = chunk_document("attendance-policy", "Attendance Policy", SAMPLE)
    second = chunk_document("attendance-policy", "Attendance Policy", SAMPLE)
    assert [c.record_id for c in first] == [c.record_id for c in second]
    assert [c.record_id for c in first] == [
        "doc:attendance-policy#0",
        "doc:attendance-policy#1",
        "doc:attendance-policy#2",
    ]
    assert [c.chunk_no for c in first] == [0, 1, 2]


def test_chunk_ids_do_not_shift_when_a_section_is_added_at_the_end() -> None:
    """Appending a section must not renumber existing citations."""
    extended = SAMPLE + "\n## 4. Medical leave\nApproved medical leave is excluded.\n"
    before = chunk_document("attendance-policy", "Attendance Policy", SAMPLE)
    after = chunk_document("attendance-policy", "Attendance Policy", extended)
    assert [c.record_id for c in after][: len(before)] == [c.record_id for c in before]
    assert len(after) == len(before) + 1


def test_long_sections_are_windowed_with_overlap() -> None:
    body = "# T\n\n## Big\n" + " ".join(f"word{i}" for i in range(1200))
    chunks = chunk_document("big", "Big", body, max_tokens=200, overlap_ratio=0.15)
    assert len(chunks) > 1
    assert all(c.token_count <= 200 for c in chunks)
    # Consecutive windows share context.
    first_words = set(chunks[0].text.split())
    second_words = set(chunks[1].text.split())
    assert first_words & second_words, "windows must overlap"


def test_token_count_floor() -> None:
    assert count_tokens("") == 1
    assert count_tokens("one two three") == 3


def test_chunk_carries_metadata() -> None:
    chunks = chunk_document(
        "placement-policy", "Placement Policy", SAMPLE,
        access_scope="public", updated_at="2026-09-01",
    )
    assert all(c.title == "Placement Policy" for c in chunks)
    assert all(c.doc_id == "placement-policy" for c in chunks)
    assert all(c.content_hash for c in chunks)
    assert all(c.access_scope == "public" for c in chunks)


def test_access_scope_survives_chunking() -> None:
    chunks = chunk_document(
        "student-record", "Student Record", SAMPLE, access_scope="student:S102"
    )
    assert all(c.access_scope == "student:S102" for c in chunks)


# --------------------------------------------------------------------------
# Pipeline-level tests (need the generated corpus)
# --------------------------------------------------------------------------


def _corpus_available() -> bool:
    return (settings.synthetic_dir / "students.csv").exists() and settings.raw_dir.exists()


def test_ingest_is_idempotent(temp_db) -> None:
    if not _corpus_available():
        import pytest

        pytest.skip("run scripts/generate_data.py first")

    from app.db import init_db, query_one
    from app.ingest.pipeline import ingest_all

    init_db()
    first = ingest_all()
    assert first.documents > 0, "expected documents to be ingested"
    assert not first.errors, first.errors
    after_first = query_one("SELECT COUNT(*) AS n FROM chunks")
    assert after_first is not None

    second = ingest_all()
    assert second.documents == 0, "re-ingest must change no documents"
    assert second.chunks == 0, "re-ingest must write no chunks"
    assert second.skipped_unchanged == first.documents
    after_second = query_one("SELECT COUNT(*) AS n FROM chunks")
    assert after_second is not None
    assert after_second["n"] == after_first["n"], "corpus size changed on re-ingest"


def test_record_cards_are_created_for_structured_rows(temp_db) -> None:
    if not _corpus_available():
        import pytest

        pytest.skip("run scripts/generate_data.py first")

    from app.db import init_db, query_one
    from app.ingest.pipeline import ingest_all

    init_db()
    ingest_all()

    student_card = query_one("SELECT * FROM chunks WHERE record_id = 'db:students:S102'")
    assert student_card is not None
    assert student_card["access_scope"] == "student:S102"
    assert "CGPA" in student_card["text"]

    role_card = query_one("SELECT * FROM chunks WHERE record_id = 'db:company_roles:1'")
    assert role_card is not None
    assert role_card["access_scope"] == "public"

    course_card = query_one("SELECT * FROM chunks WHERE record_id = 'db:courses:CS301'")
    assert course_card is not None


def test_benchmark_file_shape() -> None:
    path = settings.eval_dir / "benchmark.jsonl"
    if not path.exists():
        import pytest

        pytest.skip("run scripts/generate_data.py first")

    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(items) >= 120
    kinds = {item["kind"] for item in items}
    assert kinds == {
        "factoid", "policy", "numeric", "multi_hop", "placement",
        "unanswerable", "adversarial",
    }
    unanswerable = [i for i in items if not i["answerable"]]
    assert len(unanswerable) >= 15, "need enough unanswerable questions to measure abstention"
    adversarial = [i for i in items if i["kind"] == "adversarial"]
    assert len(adversarial) >= 10
    for item in items:
        assert item["question"] and isinstance(item["gold_sources"], list)


def test_injection_document_is_present_in_corpus(temp_db) -> None:
    """The adversarial fixture must actually reach the index, or the test is hollow."""
    if not _corpus_available():
        import pytest

        pytest.skip("run scripts/generate_data.py first")

    from app.db import init_db, query_one
    from app.ingest.pipeline import ingest_all

    init_db()
    ingest_all()
    row = query_one(
        "SELECT text FROM chunks WHERE doc_id = 'notice-board' AND text LIKE '%IGNORE ALL PREVIOUS%'"
    )
    assert row is not None, "the prompt-injection passage is not indexed"
