"""Semantic cache: reuse an answer when the question is close enough to a stored one.

A hit requires **all** of:

1. cosine similarity of the normalized-question embeddings >= ``cache_cosine``;
2. the same access scope (a staff answer is never served to a student);
3. none of the cited sources changed since the entry was written (compared by
   ``chunks.content_hash``), so a re-ingested policy invalidates stale answers;
4. the entry has not expired.

Entries live in MySQL (``cache_entries``). Embeddings are *not* stored: the cache
keeps an in-memory matrix rebuilt whenever the entry count changes, which is
cheap and keeps MySQL free of vectors (FAISS is the only vector store).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..core.settings import settings
from ..db import execute, query

log = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
# Keep word characters, whitespace and '%' (so "75%" survives); drop the rest.
_PUNCT_RE = re.compile(r"[^\w\s%]")


def normalize_question(question: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — the cache identity."""
    lowered = question.strip().lower()
    lowered = _PUNCT_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", lowered).strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class CacheHit:
    key: str
    answer: str
    sources: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    similarity: float = 0.0
    hits: int = 0


class SemanticCache:
    def __init__(self, index=None) -> None:
        self.index = index
        self._rows: list[dict] = []
        self._matrix = None
        self._loaded_count = -1

    @property
    def embedder(self):
        return getattr(self.index, "embedder", None)

    # --- internals ------------------------------------------------------

    def _count(self) -> int:
        rows = query("SELECT COUNT(*) AS n FROM cache_entries")
        return int(rows[0]["n"]) if rows else 0

    def _refresh(self) -> None:
        count = self._count()
        if count == self._loaded_count:
            return
        self._rows = query(
            """
            SELECT cache_key, normalized, answer, sources_json, confidence,
                   access_scope, source_hashes, expires_at, hits
            FROM cache_entries
            """
        )
        embedder = self.embedder
        if self._rows and embedder is not None:
            texts = [row["normalized"] for row in self._rows]
            self._matrix = embedder.encode(texts)
        else:
            self._matrix = None
        self._loaded_count = count

    def _sources_unchanged(self, source_hashes: dict[str, str]) -> bool:
        """True when every cited record still has the same content hash."""
        if not source_hashes:
            return True
        record_ids = list(source_hashes)
        placeholders = ", ".join("?" for _ in record_ids)
        rows = query(
            f"SELECT record_id, content_hash FROM chunks WHERE record_id IN ({placeholders})",
            tuple(record_ids),
        )
        current = {row["record_id"]: row["content_hash"] for row in rows}
        for record_id, expected in source_hashes.items():
            if current.get(record_id) != expected:
                return False
        return True

    @staticmethod
    def _parse_json(value) -> dict | list:
        if value is None:
            return {}
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return {}

    # --- public API -----------------------------------------------------

    def lookup(self, question: str, access_scope: str = "public") -> CacheHit | None:
        self._refresh()
        if not self._rows or self._matrix is None:
            return None
        embedder = self.embedder
        if embedder is None:
            return None

        vector = embedder.encode_one(normalize_question(question))
        if vector.size != self._matrix.shape[1]:
            return None
        similarities = self._matrix @ vector
        best = int(similarities.argmax())
        similarity = float(similarities[best])
        if similarity < settings.cache_cosine:
            return None

        row = self._rows[best]
        # Scope and freshness are hard gates — similarity alone is not enough.
        if row["access_scope"] != access_scope:
            return None
        try:
            expires = datetime.strptime(row["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except (TypeError, ValueError):
            expires = _now()
        if expires <= _now():
            self.invalidate(row["cache_key"])
            return None
        if not self._sources_unchanged(self._parse_json(row["source_hashes"])):
            # A cited record changed: the cached answer may now be wrong.
            self.invalidate(row["cache_key"])
            return None

        new_hits = self._bump_hits(row["cache_key"])
        sources = self._parse_json(row["sources_json"])
        return CacheHit(
            key=row["cache_key"],
            answer=row["answer"],
            sources=sources if isinstance(sources, list) else [],
            confidence=float(row["confidence"] or 0.0),
            similarity=round(similarity, 4),
            hits=new_hits,
        )

    def store(
        self,
        question: str,
        answer: str,
        sources: list[dict],
        confidence: float,
        access_scope: str = "public",
        source_hashes: dict[str, str] | None = None,
        ttl_s: int | None = None,
    ) -> str:
        normalized = normalize_question(question)
        key = hashlib.sha1(f"{access_scope}|{normalized}".encode("utf-8")).hexdigest()
        expires = _now() + timedelta(seconds=ttl_s or settings.cache_ttl_s)
        execute(
            """
            REPLACE INTO cache_entries
                (cache_key, question, normalized, answer, sources_json, confidence,
                 access_scope, source_hashes, hits, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                key,
                question,
                normalized,
                answer,
                json.dumps(sources),
                confidence,
                access_scope,
                json.dumps(source_hashes or {}),
                _iso(_now()),
                _iso(expires),
            ),
        )
        self._loaded_count = -1
        return key

    def _bump_hits(self, key: str) -> int:
        # Increment in SQL rather than from the in-memory row, which is stale
        # between refreshes and would otherwise cap the counter at 1.
        try:
            execute("UPDATE cache_entries SET hits = hits + 1 WHERE cache_key = ?", (key,))
            rows = query("SELECT hits FROM cache_entries WHERE cache_key = ?", (key,))
            return int(rows[0]["hits"]) if rows else 0
        except Exception as exc:  # pragma: no cover
            log.debug("could not bump cache hits: %s", exc)
            return 0

    def invalidate(self, key: str) -> None:
        execute("DELETE FROM cache_entries WHERE cache_key = ?", (key,))
        self._loaded_count = -1

    def invalidate_all(self) -> None:
        execute("DELETE FROM cache_entries")
        self._loaded_count = -1

    def stats(self) -> dict[str, int]:
        rows = query("SELECT COUNT(*) AS n, COALESCE(SUM(hits), 0) AS h FROM cache_entries")
        row = rows[0] if rows else {"n": 0, "h": 0}
        return {"entries": int(row["n"]), "hits": int(row["h"])}

    def status_detail(self) -> str:
        stats = self.stats()
        return f"{stats['entries']} cached answers, {stats['hits']} hits"
