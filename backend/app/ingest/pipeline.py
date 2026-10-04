"""The ingestion pipeline.

Order matters: structured rows are loaded into MySQL first, because their
"record cards" are derived from the rows and are indexed alongside the document
chunks. Everything is keyed by content hash, so re-ingesting an unchanged corpus
writes nothing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..core.settings import settings
from ..db import execute, query, query_one
from .chunking import Chunk, chunk_document, content_hash
from .loaders import discover_documents, load_document
from .record_cards import build_record_cards
from .structured import load_structured

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    documents: int = 0
    chunks: int = 0
    records: int = 0
    skipped_unchanged: int = 0
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _store_chunk(chunk: Chunk) -> None:
    execute(
        """
        INSERT INTO chunks (record_id, doc_id, chunk_no, title, section, page, text,
                            token_count, access_scope, content_hash, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON DUPLICATE KEY UPDATE
            title = VALUES(title),
            section = VALUES(section),
            page = VALUES(page),
            text = VALUES(text),
            token_count = VALUES(token_count),
            access_scope = VALUES(access_scope),
            content_hash = VALUES(content_hash),
            updated_at = VALUES(updated_at)
        """,
        (
            chunk.record_id, chunk.doc_id, chunk.chunk_no, chunk.title, chunk.section,
            chunk.page, chunk.text, chunk.token_count, chunk.access_scope,
            chunk.content_hash, chunk.updated_at or _now(),
        ),
    )


def _delete_document_chunks(doc_id: str) -> None:
    """Remove chunks of a re-ingested document that no longer exist."""
    execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))


def ingest_documents(root: Path, force: bool = False) -> tuple[int, int, int, list[str]]:
    """Ingest every loadable document under ``root``.

    Returns (documents_changed, chunks_written, skipped_unchanged, errors).
    """
    errors: list[str] = []
    changed_docs = 0
    written = 0
    skipped = 0

    for path in discover_documents(root):
        try:
            loaded = load_document(path)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
            continue

        if not loaded.text.strip():
            errors.append(f"{path.name}: no extractable text")
            continue

        text_hash = content_hash(loaded.text)
        existing = query_one("SELECT * FROM documents WHERE doc_id = ?", (loaded.doc_id,))

        if existing and existing["content_hash"] == text_hash and not force:
            skipped += 1
            continue

        chunks = chunk_document(
            doc_id=loaded.doc_id,
            title=loaded.title,
            text=loaded.text,
            access_scope="public",
            updated_at=_now(),
        )
        if not chunks:
            errors.append(f"{path.name}: chunking produced nothing")
            continue

        version = int(existing["version"]) + 1 if existing else 1
        execute(
            """
            INSERT INTO documents (doc_id, title, source_path, doc_type, content_hash,
                                   access_scope, version, updated_at, indexed_at)
            VALUES (?, ?, ?, ?, ?, 'public', ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                source_path = VALUES(source_path),
                content_hash = VALUES(content_hash),
                version = VALUES(version),
                updated_at = VALUES(updated_at),
                indexed_at = VALUES(indexed_at)
            """,
            (loaded.doc_id, loaded.title, loaded.source_path, loaded.doc_type,
             text_hash, version, _now(), _now()),
        )

        _delete_document_chunks(loaded.doc_id)
        for chunk in chunks:
            _store_chunk(chunk)
            written += 1
        changed_docs += 1

    return changed_docs, written, skipped, errors


def ingest_record_cards() -> tuple[int, list[str]]:
    """Upsert the structured record cards from the current MySQL rows.

    Cards are derived data, so rows that no longer exist must disappear. Rather
    than deleting every card and re-inserting (which would throw away 6k
    embeddings on every ingest), stale ids are deleted and the rest upserted,
    preserving their embeddings when the text is unchanged.
    """
    errors: list[str] = []
    try:
        cards = build_record_cards()
    except Exception as exc:
        return 0, [f"record cards: {exc}"]

    fresh_ids = {card.record_id for card in cards}
    existing = query("SELECT record_id FROM chunks WHERE record_id LIKE 'db:%'")
    stale = [row["record_id"] for row in existing if row["record_id"] not in fresh_ids]
    for record_id in stale:
        execute("DELETE FROM chunks WHERE record_id = ?", (record_id,))

    for card in cards:
        try:
            # Skip the write when the card is byte-identical, so its embedding survives.
            current = query_one(
                "SELECT content_hash FROM chunks WHERE record_id = ?", (card.record_id,)
            )
            if current and current["content_hash"] == card.content_hash:
                continue
            _store_chunk(card)
        except Exception as exc:
            errors.append(f"{card.record_id}: {exc}")
    return len(cards), errors


def ingest_all(
    path: Path | str | None = None,
    structured_dir: Path | str | None = None,
    force: bool = False,
) -> IngestResult:
    """Full ingestion: structured rows -> record cards -> documents -> index."""
    started = time.perf_counter()
    result = IngestResult()

    doc_root = Path(path) if path else settings.raw_dir
    structured = Path(structured_dir) if structured_dir else settings.synthetic_dir

    if structured.exists():
        structured_result = load_structured(structured)
        result.records = structured_result.total
        result.errors.extend(structured_result.errors)
        log.info("loaded %d structured rows", structured_result.total)

    card_count, card_errors = ingest_record_cards()
    result.records += card_count
    result.errors.extend(card_errors)

    docs, chunks, skipped, doc_errors = ingest_documents(doc_root, force=force)
    result.documents = docs
    result.chunks = chunks
    result.skipped_unchanged = skipped
    result.errors.extend(doc_errors)

    result.duration_ms = round((time.perf_counter() - started) * 1000, 2)
    log.info(
        "ingest complete: %d documents, %d chunks, %d records, %d skipped",
        result.documents, result.chunks, result.records, result.skipped_unchanged,
    )
    return result


def corpus_stats() -> dict[str, int]:
    """Counts used by the CLI summary and the health endpoint."""
    docs = query_one("SELECT COUNT(*) AS n FROM documents")
    chunks = query_one("SELECT COUNT(*) AS n FROM chunks")
    db_chunks = query_one("SELECT COUNT(*) AS n FROM chunks WHERE record_id LIKE 'db:%'")
    # Vectors are not stored here: FAISS holds them and maps back to record_ids,
    # so there is nothing in MySQL to count as "embedded". ``vectors`` therefore
    # mirrors the chunk count and exists only so the CLI summary stays stable.
    total = int(chunks["n"]) if chunks else 0
    return {
        "documents": int(docs["n"]) if docs else 0,
        "chunks": total,
        "embedded": total,
        "record_cards": int(db_chunks["n"]) if db_chunks else 0,
    }
