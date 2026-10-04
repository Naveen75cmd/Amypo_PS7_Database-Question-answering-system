"""The hybrid retrieval index.

Pipeline: dense top-N (FAISS when available, numpy otherwise) + BM25 top-N ->
reciprocal rank fusion -> feature-based rerank -> top-k, with metadata and
access filtering applied *before* ranking so an unauthorized chunk can never
surface even as a low-ranked result.

The index lives in memory and is rebuilt from MySQL on demand: chunk text,
metadata and access scope are read from MySQL, while the embedding vectors live
only in FAISS and are regenerated on load.
"""

from __future__ import annotations

import logging
import pickle
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from ..core.settings import settings
from ..db import query
from .embeddings import Embedder, load_embedder
from .tokenize import tokenize, tokenize_query

log = logging.getLogger(__name__)

RerankerKind = Literal["feature", "cross_encoder", "none"]


@dataclass
class ChunkRecord:
    record_id: str
    doc_id: str
    chunk_no: int
    title: str
    section: str | None
    page: int | None
    text: str
    token_count: int
    access_scope: str
    content_hash: str
    updated_at: str
    tokens: list[str] = field(default_factory=list)


@dataclass
class Retrieved:
    record_id: str
    text: str
    title: str
    section: str | None
    updated_at: str
    access_scope: str
    dense_score: float = 0.0
    bm25_score: float = 0.0
    fused_score: float = 0.0
    rerank_score: float = 0.0
    rank: int = 0
    matched_terms: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "title": self.title,
            "section": self.section,
            "updated_at": self.updated_at,
            "dense_score": round(self.dense_score, 4),
            "bm25_score": round(self.bm25_score, 4),
            "fused_score": round(self.fused_score, 4),
            "rerank_score": round(self.rerank_score, 4),
            "rank": self.rank,
            "matched_terms": self.matched_terms[:8],
        }


class AccessFilter:
    """Retrieval-time access control. Never enforced by the prompt."""

    @staticmethod
    def allowed_scopes(user_id: str | None, role: str) -> set[str] | None:
        """Return the scopes this caller may read, or None for everything."""
        if role in settings.staff_roles:
            return None  # staff: unrestricted
        if not user_id:
            return {"public"}
        return {"public", f"student:{user_id}"}

    @staticmethod
    def permits(access_scope: str, allowed: set[str] | None) -> bool:
        if allowed is None:
            return True
        if access_scope == "public":
            return True
        if access_scope in allowed:
            return True
        # A student may read staff-visible rows only if they are also their own.
        return False


class RetrievalIndex:
    """In-memory hybrid index over the ``chunks`` table."""

    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder: Embedder = embedder or load_embedder()
        self.chunks: list[ChunkRecord] = []
        self._by_id: dict[str, int] = {}
        self.vectors: np.ndarray = np.zeros((0, self.embedder.dim), dtype=np.float32)
        self._bm25 = None
        self._faiss = None
        self._built_at: float = 0.0
        self._embed_time_ms: float = 0.0
        self._corpus_stats: dict[str, int] = {}

    # --- lifecycle ------------------------------------------------------

    @classmethod
    def load_or_build(cls, embedder: Embedder | None = None) -> "RetrievalIndex":
        index = cls(embedder=embedder)
        index.build()
        return index

    def refresh(self) -> None:
        """Rebuild from MySQL (called after ingestion)."""
        self.build()

    @property
    def is_empty(self) -> bool:
        return not self.chunks

    def build(self) -> None:
        started = time.perf_counter()
        rows = query(
            """
            SELECT record_id, doc_id, chunk_no, title, section, page, text,
                   token_count, access_scope, content_hash, updated_at
            FROM chunks
            """
        )
        self.chunks = []
        self._by_id = {}
        vectors: list[np.ndarray] = []

        for row in rows:
            record = ChunkRecord(
                record_id=row["record_id"],
                doc_id=row["doc_id"],
                chunk_no=int(row["chunk_no"]),
                title=row["title"] or "",
                section=row["section"],
                page=row["page"],
                text=row["text"] or "",
                token_count=int(row["token_count"] or 0),
                access_scope=row["access_scope"] or "public",
                content_hash=row["content_hash"] or "",
                updated_at=row["updated_at"] or "",
                tokens=tokenize(row["text"] or ""),
            )
            self._by_id[record.record_id] = len(self.chunks)
            self.chunks.append(record)
            vectors.append(np.zeros(self.embedder.dim, dtype=np.float32))

        # Vectors live only in FAISS. MySQL stores chunk text, metadata and
        # access_scope, so every chunk is encoded on load instead of read back
        # from an embedding column.
        missing = list(range(len(self.chunks)))
        if missing:
            self._embed_missing(missing, vectors)

        self.vectors = (
            np.vstack(vectors).astype(np.float32)
            if vectors
            else np.zeros((0, self.embedder.dim), dtype=np.float32)
        )
        self._build_bm25()
        self._build_faiss()
        self._built_at = time.perf_counter()
        self._corpus_stats = {
            "chunks": len(self.chunks),
            "embedded": len(self.chunks) - len(missing) + len(missing),
            "embedded_new": len(missing),
        }
        log.info(
            "index built: %d chunks (%d newly embedded) in %.0f ms",
            len(self.chunks), len(missing), (self._built_at - started) * 1000,
        )

    def _embed_missing(self, indexes: list[int], vectors: list[np.ndarray]) -> None:
        started = time.perf_counter()
        texts = [self.chunks[i].text for i in indexes]
        batch_size = 64
        for start in range(0, len(texts), batch_size):
            batch_texts = texts[start : start + batch_size]
            batch_indexes = indexes[start : start + batch_size]
            try:
                encoded = self.embedder.encode(batch_texts, batch_size=batch_size)
            except Exception as exc:  # pragma: no cover - model failure mid-build
                log.warning("embedding batch failed (%s); storing zeros", exc)
                encoded = np.zeros((len(batch_texts), self.embedder.dim), dtype=np.float32)
            for offset, chunk_index in enumerate(batch_indexes):
                vector = np.asarray(encoded[offset], dtype=np.float32)
                vectors[chunk_index] = vector
        self._embed_time_ms = (time.perf_counter() - started) * 1000

    def _build_bm25(self) -> None:
        if not self.chunks:
            self._bm25 = None
            return
        from rank_bm25 import BM25Okapi

        corpus = [c.tokens or tokenize(c.text) for c in self.chunks]
        try:
            self._bm25 = BM25Okapi(corpus)
        except Exception as exc:  # pragma: no cover - empty corpus edge case
            log.warning("BM25 build failed (%s); falling back to dense only", exc)
            self._bm25 = None

    def _build_faiss(self) -> None:
        self._faiss = None
        if self.vectors.size == 0:
            return
        try:
            import faiss  # type: ignore

            index = faiss.IndexFlatIP(self.vectors.shape[1])
            index.add(self.vectors)
            self._faiss = index
        except Exception:
            self._faiss = None  # numpy cosine is the fallback

    def stats(self) -> dict[str, Any]:
        return {
            "chunks": len(self.chunks),
            "dim": int(self.vectors.shape[1]) if self.vectors.size else self.embedder.dim,
            "backend": "faiss" if self._faiss is not None else "numpy",
            "embedder": self.embedder.status(),
            "embed_time_ms": round(self._embed_time_ms, 1),
            **self._corpus_stats,
        }

    # --- search ---------------------------------------------------------

    def dense_search(
        self, query_text: str, top_k: int, allowed: set[str] | None
    ) -> list[tuple[int, float]]:
        if self.vectors.size == 0:
            return []
        query_vector = self.embedder.encode_one(query_text).astype(np.float32)
        if query_vector.size != self.vectors.shape[1]:
            return []

        if self._faiss is not None:
            # Over-fetch, then filter by access and slice to top_k.
            fetch = min(len(self.chunks), max(top_k * 4, top_k))
            scores, indexes = self._faiss.search(query_vector.reshape(1, -1), fetch)
            candidates = [
                (int(idx), float(score))
                for idx, score in zip(indexes[0], scores[0])
                if idx >= 0
            ]
        else:
            sims = self.vectors @ query_vector
            order = np.argsort(-sims)
            candidates = [(int(i), float(sims[i])) for i in order[: max(top_k * 4, top_k)]]

        out: list[tuple[int, float]] = []
        for idx, score in candidates:
            if AccessFilter.permits(self.chunks[idx].access_scope, allowed):
                out.append((idx, score))
            if len(out) >= top_k:
                break
        return out

    def bm25_search(
        self, query_text: str, top_k: int, allowed: set[str] | None
    ) -> list[tuple[int, float]]:
        if self._bm25 is None or not self.chunks:
            return []
        tokens = tokenize_query(query_text)
        if not tokens:
            return []
        scores = np.asarray(self._bm25.get_scores(tokens), dtype=np.float32)
        order = np.argsort(-scores)
        out: list[tuple[int, float]] = []
        for idx in order:
            if scores[idx] <= 0:
                break
            if AccessFilter.permits(self.chunks[idx].access_scope, allowed):
                out.append((int(idx), float(scores[idx])))
            if len(out) >= top_k:
                break
        return out

    @staticmethod
    def reciprocal_rank_fusion(
        ranked_lists: list[list[tuple[int, float]]],
        k: int | None = None,
        weights: list[float] | None = None,
    ) -> list[tuple[int, float]]:
        """Weighted RRF: score = sum over lists of weight / (k + rank).

        Rank-based, so the two very different score scales never need
        calibrating. The weights let a retriever that is known to be weak on
        this corpus contribute proportionally less, which is measured rather
        than assumed: see ``fusion_weights``.
        """
        k = k or settings.rrf_k
        weights = weights or [1.0] * len(ranked_lists)
        fused: dict[int, float] = {}
        for weight, ranked in zip(weights, ranked_lists):
            for rank, (idx, _score) in enumerate(ranked, start=1):
                fused[idx] = fused.get(idx, 0.0) + weight / (k + rank)
        return sorted(fused.items(), key=lambda item: -item[1])

    def fusion_weights(self) -> tuple[float, float]:
        """(dense_weight, bm25_weight) for RRF.

        The deterministic hash embedder has no semantics — it measures lexical
        overlap — so its ranking is a noisy echo of BM25 and fusing it at full
        weight measurably *hurts* precision. When it is the active backend we
        down-weight dense retrieval accordingly. With a real sentence-transformer
        both retrievers are trusted equally.
        """
        from .embeddings import HashEmbedder

        if isinstance(self.embedder, HashEmbedder):
            return settings.dense_fusion_weight_fallback, 1.0
        return 1.0, 1.0

    def rerank(
        self, query_text: str, candidates: list[tuple[int, float]], top_k: int,
        kind: RerankerKind | None = None,
    ) -> list[Retrieved]:
        kind = kind or settings.reranker  # type: ignore[assignment]
        if kind == "cross_encoder":
            ranked = self._cross_encoder_rerank(query_text, candidates)
            if ranked is not None:
                return ranked[:top_k]
            kind = "feature"  # degrade rather than fail

        query_tokens = set(tokenize_query(query_text))
        results: list[Retrieved] = []
        for idx, fused in candidates:
            chunk = self.chunks[idx]
            result = Retrieved(
                record_id=chunk.record_id,
                text=chunk.text,
                title=chunk.title,
                section=chunk.section,
                updated_at=chunk.updated_at,
                access_scope=chunk.access_scope,
                fused_score=fused,
            )
            if kind == "none":
                result.rerank_score = fused
            else:
                result.rerank_score = self._feature_score(query_text, query_tokens, chunk, result)
            results.append(result)

        results.sort(key=lambda r: -r.rerank_score)
        for position, result in enumerate(results, start=1):
            result.rank = position
        return results[:top_k]

    def _feature_score(
        self, query_text: str, query_tokens: set[str], chunk: ChunkRecord, result: Retrieved
    ) -> float:
        """Explainable feature-based reranker.

        Deliberately a small linear blend of interpretable signals rather than a
        learned black box, so every ranking can be justified in one sentence.
        """
        chunk_tokens = set(chunk.tokens)
        overlap = query_tokens & chunk_tokens
        result.matched_terms = sorted(overlap)

        coverage = len(overlap) / max(1, len(query_tokens))
        # Title/section hits are strong evidence the chunk is on-topic.
        title_tokens = set(tokenize(chunk.title))
        section_tokens = set(tokenize(chunk.section or ""))
        title_hit = 1.0 if query_tokens & title_tokens else 0.0
        section_hit = 1.0 if query_tokens & section_tokens else 0.0
        # Identifier matches (course codes, student ids) are near-deterministic.
        identifiers = {t for t in query_tokens if any(ch.isdigit() for ch in t)}
        identifier_hit = len(identifiers & chunk_tokens) / max(1, len(identifiers)) if identifiers else 0.0
        # Prefer focused chunks over sprawling ones.
        length_penalty = min(1.0, chunk.token_count / 400.0)

        dense = self._dense_similarity(query_text, chunk)
        result.dense_score = dense
        dense_weight = self.dense_feature_weight()

        score = (
            dense_weight * dense
            + 0.26 * coverage
            + 0.16 * identifier_hit
            + 0.10 * title_hit
            + 0.06 * section_hit
            + 0.08 * min(1.0, result.fused_score * 30)
            - 0.04 * length_penalty
            - self._superseded_penalty(chunk)
        )
        return float(score)

    @staticmethod
    def _superseded_penalty(chunk: ChunkRecord) -> float:
        """Down-rank documents that are explicitly marked as superseded.

        The corpus deliberately contains a retired attendance policy. Both it and
        the current one match the same question almost equally well, so without
        this the retired rule can rank first and the answer layer has to clean up
        the mess. Detecting it at ranking time is cheaper and more honest than
        hoping the generator prefers the newer text.
        """
        haystack = f"{chunk.title} {chunk.section or ''}".lower()
        if "superseded" in haystack or "2019 version" in haystack:
            return 0.12
        return 0.0

    def dense_feature_weight(self) -> float:
        """Weight of dense similarity in the feature reranker.

        A semantic embedder earns its full weight; the hash fallback does not,
        because its cosine similarity is just a smoothed lexical overlap that
        the other lexical features already capture.
        """
        from .embeddings import HashEmbedder

        if isinstance(self.embedder, HashEmbedder):
            return settings.reranker_dense_weight_fallback
        return settings.reranker_dense_weight

    def _dense_similarity(self, query_text: str, chunk: ChunkRecord) -> float:
        idx = self._by_id.get(chunk.record_id)
        if idx is None or self.vectors.size == 0:
            return 0.0
        query_vector = self.embedder.encode_one(query_text).astype(np.float32)
        if query_vector.size != self.vectors.shape[1]:
            return 0.0
        return float(np.clip(np.dot(self.vectors[idx], query_vector), -1.0, 1.0))

    def _cross_encoder_rerank(
        self, query_text: str, candidates: list[tuple[int, float]]
    ) -> list[Retrieved] | None:
        """Optional cross-encoder path. Returns None when unavailable."""
        try:
            from sentence_transformers import CrossEncoder
        except Exception:
            return None
        if not candidates:
            return []
        try:
            model = self._cross_encoder_model()
            pairs = [(query_text, self.chunks[idx].text) for idx, _ in candidates]
            scores = model.predict(pairs, show_progress_bar=False)
        except Exception as exc:  # pragma: no cover
            log.warning("cross-encoder rerank failed (%s); using features", exc)
            return None

        results: list[Retrieved] = []
        for (idx, fused), score in zip(candidates, scores):
            chunk = self.chunks[idx]
            results.append(
                Retrieved(
                    record_id=chunk.record_id,
                    text=chunk.text,
                    title=chunk.title,
                    section=chunk.section,
                    updated_at=chunk.updated_at,
                    access_scope=chunk.access_scope,
                    fused_score=fused,
                    rerank_score=float(score),
                )
            )
        results.sort(key=lambda r: -r.rerank_score)
        for position, result in enumerate(results, start=1):
            result.rank = position
        return results

    def _cross_encoder_model(self):  # pragma: no cover - optional dependency
        cached = getattr(self, "_ce_model", None)
        if cached is None:
            from sentence_transformers import CrossEncoder

            self._ce_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        return self._ce_model

    # --- public API -----------------------------------------------------

    def retrieve(
        self,
        query_text: str,
        top_k: int | None = None,
        user_id: str | None = None,
        role: str = "student",
        mode: Literal["dense", "bm25", "hybrid", "hybrid_rerank"] = "hybrid_rerank",
        reranker: RerankerKind | None = None,
        dense_k: int | None = None,
        bm25_k: int | None = None,
    ) -> list[Retrieved]:
        """Retrieve passages, honouring the caller's access scope."""
        top_k = top_k or settings.final_top_k
        allowed = AccessFilter.allowed_scopes(user_id, role)

        if mode == "dense":
            ranked = self.dense_search(query_text, top_k, allowed)
            return self._as_retrieved(ranked, top_k)
        if mode == "bm25":
            ranked = self.bm25_search(query_text, top_k, allowed)
            return self._as_retrieved(ranked, top_k)

        dense = self.dense_search(query_text, dense_k or settings.dense_top_k, allowed)
        sparse = self.bm25_search(query_text, bm25_k or settings.bm25_top_k, allowed)
        fused = self.reciprocal_rank_fusion(
            [dense, sparse], weights=list(self.fusion_weights())
        )

        dense_scores = dict(dense)
        sparse_scores = dict(sparse)

        if mode == "hybrid":
            results = self._as_retrieved(fused, top_k)
            for result in results:
                idx = self._by_id.get(result.record_id)
                if idx is not None:
                    result.dense_score = dense_scores.get(idx, 0.0)
                    result.bm25_score = sparse_scores.get(idx, 0.0)
            return results

        results = self.rerank(query_text, fused, top_k, kind=reranker)
        for result in results:
            idx = self._by_id.get(result.record_id)
            if idx is not None:
                result.bm25_score = sparse_scores.get(idx, 0.0)
        return results

    def _as_retrieved(self, ranked: list[tuple[int, float]], top_k: int) -> list[Retrieved]:
        results: list[Retrieved] = []
        for position, (idx, score) in enumerate(ranked[:top_k], start=1):
            chunk = self.chunks[idx]
            results.append(
                Retrieved(
                    record_id=chunk.record_id,
                    text=chunk.text,
                    title=chunk.title,
                    section=chunk.section,
                    updated_at=chunk.updated_at,
                    access_scope=chunk.access_scope,
                    fused_score=score,
                    rerank_score=score,
                    rank=position,
                )
            )
        return results

    def get_chunk(self, record_id: str) -> ChunkRecord | None:
        idx = self._by_id.get(record_id)
        return self.chunks[idx] if idx is not None else None

    def chunk_hashes(self, record_ids: list[str]) -> dict[str, str]:
        """Content hashes for cache validation."""
        out: dict[str, str] = {}
        for record_id in record_ids:
            chunk = self.get_chunk(record_id)
            if chunk is not None:
                out[record_id] = chunk.content_hash
        return out

    # --- persistence of the whole index (optional speed-up) -------------

    def save(self, path) -> None:
        from pathlib import Path

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as fh:
            pickle.dump(
                {
                    "chunks": self.chunks,
                    "vectors": self.vectors,
                    "embedder": self.embedder.status(),
                },
                fh,
                protocol=pickle.HIGHEST_PROTOCOL,
            )

    @classmethod
    def load(cls, path, embedder: Embedder | None = None) -> "RetrievalIndex":
        from pathlib import Path

        with Path(path).open("rb") as fh:
            payload = pickle.load(fh)
        index = cls(embedder=embedder)
        index.chunks = payload["chunks"]
        index.vectors = payload["vectors"]
        index._by_id = {c.record_id: i for i, c in enumerate(index.chunks)}
        index._build_bm25()
        index._build_faiss()
        return index
