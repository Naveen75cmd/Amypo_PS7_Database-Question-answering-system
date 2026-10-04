"""Phase 5: the semantic cache's hit rules.

A deterministic fake embedder is used so the cosine gate, the scope gate and the
staleness gate can be tested precisely, independent of the real embedder.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.cache.semantic_cache import SemanticCache, normalize_question


class _FakeEmbedder:
    """Maps a question to a unit vector by keyword, so cosines are exact."""

    dim = 4

    def _vec(self, text: str) -> np.ndarray:
        lowered = normalize_question(text)
        if "attendance" in lowered:
            return np.array([1.0, 0.0, 0.0, 0.0])
        if "curfew" in lowered:
            return np.array([0.0, 1.0, 0.0, 0.0])
        return np.array([0.0, 0.0, 1.0, 0.0])

    def encode_one(self, text: str) -> np.ndarray:
        return self._vec(text)

    def encode(self, texts, batch_size: int = 64) -> np.ndarray:
        return np.vstack([self._vec(t) for t in texts])


class _FakeIndex:
    def __init__(self) -> None:
        self.embedder = _FakeEmbedder()


@pytest.fixture()
def cache(temp_db) -> SemanticCache:
    return SemanticCache(_FakeIndex())


def test_normalization_ignores_case_and_punctuation() -> None:
    assert normalize_question("  What is MY CGPA?!  ") == "what is my cgpa"
    assert normalize_question("what is my cgpa") == normalize_question("What is my CGPA?")


def test_exact_question_hits(cache) -> None:
    cache.store(
        "What is the attendance policy?",
        "75% [S1]",
        [{"record_id": "doc:attendance-policy#0", "snippet": "75%"}],
        0.9,
        "public",
    )
    hit = cache.lookup("What is the attendance policy?", "public")
    assert hit is not None
    assert hit.answer == "75% [S1]"
    assert hit.similarity >= 0.99


def test_dissimilar_question_misses(cache) -> None:
    cache.store("What is the attendance policy?", "75%", [], 0.9, "public")
    assert cache.lookup("What is the hostel curfew?", "public") is None


def test_different_access_scope_misses(cache) -> None:
    cache.store("What is the attendance policy?", "75%", [], 0.9, "student:S102")
    assert cache.lookup("What is the attendance policy?", "public") is None
    assert cache.lookup("What is the attendance policy?", "student:S102") is not None


def test_cosine_threshold_is_enforced(cache, monkeypatch) -> None:
    from app.core.settings import settings

    # A 90-degree "no match" vector cannot pass even a permissive threshold, and
    # an identical vector fails a threshold above 1.0.
    cache.store("What is the attendance policy?", "75%", [], 0.9, "public")
    monkeypatch.setattr(settings, "cache_cosine", 1.5, raising=False)
    assert cache.lookup("What is the attendance policy?", "public") is None
    monkeypatch.setattr(settings, "cache_cosine", 0.9, raising=False)
    assert cache.lookup("What is the attendance policy?", "public") is not None


def test_changed_source_invalidates_the_entry(cache) -> None:
    # A cited record with a hash that does not match MySQL means the source moved.
    cache.store(
        "What is the attendance policy?",
        "75%",
        [{"record_id": "db:students:S102", "snippet": "x"}],
        0.9,
        "public",
        {"db:students:S102": "hash-from-a-previous-ingest"},
    )
    assert cache.lookup("What is the attendance policy?", "public") is None
    assert cache.stats()["entries"] == 0, "a stale entry must be dropped, not kept"


def test_expired_entry_misses(cache) -> None:
    cache.store("What is the attendance policy?", "75%", [], 0.9, "public", ttl_s=-5)
    assert cache.lookup("What is the attendance policy?", "public") is None


def test_hits_are_counted(cache) -> None:
    cache.store("What is the attendance policy?", "75%", [], 0.9, "public")
    cache.lookup("What is the attendance policy?", "public")
    cache.lookup("What is the attendance policy?", "public")
    assert cache.stats()["hits"] == 2
