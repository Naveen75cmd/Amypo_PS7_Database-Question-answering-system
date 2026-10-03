"""Embedding backend.

Two implementations behind one interface:

* ``SentenceTransformerEmbedder`` — the real model, used when
  ``sentence-transformers`` is installed and ``AMYPO_ALLOW_REAL_MODELS`` is on.
* ``HashEmbedder`` — a deterministic hashing vectorizer with the same output
  shape. It is not semantically strong, but it is stable, dependency-free and
  keeps the entire pipeline (and the test suite) runnable offline with no
  downloads. Every score it produces is reproducible.

The active backend is reported by ``/api/v1/health`` so a demo never silently
claims real model quality while running the fallback.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Iterable

import numpy as np

from ..core.settings import settings

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[A-Za-z0-9]+")


class Embedder:
    """Interface: encode texts into L2-normalized float32 vectors."""

    name: str = "base"
    dim: int = settings.embed_dim

    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        raise NotImplementedError

    def encode_one(self, text: str) -> np.ndarray:
        return self.encode([text])[0]

    def status(self) -> str:
        return self.name


class HashEmbedder(Embedder):
    """Deterministic hashed bag-of-words with sublinear term weighting.

    Cosine similarity between two vectors is a reasonable lexical-overlap proxy,
    which is exactly what the fallback needs: it must never invent semantics it
    does not have.
    """

    name = "hash-fallback"

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or settings.embed_dim

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        counts: dict[str, int] = {}
        for word in _WORD_RE.findall(text.lower()):
            counts[word] = counts.get(word, 0) + 1
        if not counts:
            return vec
        for word, count in counts.items():
            digest = hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            # Sublinear weighting keeps repeated words from dominating.
            vec[index] += sign * (1.0 + math.log(count))
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec

    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self._vector(t) for t in texts]).astype(np.float32)


class SentenceTransformerEmbedder(Embedder):
    name = "sentence-transformers"

    def __init__(self, model_name: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name or settings.embed_model_name
        self._model = SentenceTransformer(self.model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        log.info("loaded embedding model %s (dim=%d)", self.model_name, self.dim)

    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = self._model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


def load_embedder() -> Embedder:
    """Pick the best available embedder, degrading to the deterministic one."""
    if not settings.allow_real_models:
        log.info("real models disabled; using hash embedder")
        return HashEmbedder()
    try:
        return SentenceTransformerEmbedder()
    except Exception as exc:  # ImportError, network failure, corrupt cache
        log.warning("sentence-transformers unavailable (%s); using hash embedder", exc)
        return HashEmbedder()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity for already-normalized vectors (plain dot product)."""
    if a.size == 0 or b.size == 0 or a.shape != b.shape:
        return 0.0
    return float(np.clip(np.dot(a, b), -1.0, 1.0))


def vectors_to_blob(matrix: np.ndarray) -> bytes:
    return np.asarray(matrix, dtype=np.float32).tobytes()


def blob_to_vector(blob: bytes | None) -> np.ndarray | None:
    if blob is None:
        return None
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    if not blob:
        return None
    return np.frombuffer(blob, dtype=np.float32)


def stack(vectors: Iterable[np.ndarray]) -> np.ndarray:
    vectors = list(vectors)
    if not vectors:
        return np.zeros((0, settings.embed_dim), dtype=np.float32)
    return np.vstack(vectors).astype(np.float32)
