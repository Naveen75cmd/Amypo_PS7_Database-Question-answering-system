"""Section-aware chunking with stable record ids.

Chunk boundaries follow markdown headings so a chunk is always about one topic.
Record ids are derived from the document id and the *ordinal position of the
section*, not from byte offsets, so re-ingesting an unchanged document produces
identical ids. That is what lets the semantic cache validate its sources.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Iterable

from ..core.settings import settings

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# Prose in these documents is wrapped at ~80 columns, so a sentence can span a
# line break. Collapsing *all* whitespace runs (including newlines) keeps a
# chunk readable and makes phrase matching reliable.
_WS_RE = re.compile(r"\s+")


@dataclass
class Chunk:
    record_id: str
    doc_id: str
    chunk_no: int
    title: str
    section: str
    page: int | None
    text: str
    token_count: int
    access_scope: str = "public"
    content_hash: str = ""
    updated_at: str = ""

    def as_row(self) -> dict:
        return {
            "record_id": self.record_id,
            "doc_id": self.doc_id,
            "chunk_no": self.chunk_no,
            "title": self.title,
            "section": self.section,
            "page": self.page,
            "text": self.text,
            "token_count": self.token_count,
            "access_scope": self.access_scope,
            "content_hash": self.content_hash,
            "updated_at": self.updated_at,
        }


@dataclass
class Section:
    title: str
    body: str
    page: int | None = None
    lines: list[str] = field(default_factory=list)


def count_tokens(text: str) -> int:
    """Cheap whitespace token count, with a floor for punctuation-heavy text."""
    return max(1, len(text.split()))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def stable_record_id(doc_id: str, chunk_no: int) -> str:
    """``doc:<doc_id>#<n>`` — the citation id scheme for document chunks."""
    return f"doc:{doc_id}#{chunk_no}"


def db_record_id(table: str, pk: object) -> str:
    """``db:<table>:<pk>`` — the citation id scheme for structured rows."""
    return f"db:{table}:{pk}"


def split_sections(markdown: str, default_title: str = "Document") -> list[Section]:
    """Split markdown into sections keyed by headings.

    Text before the first heading becomes a section titled after the document.
    The top-level ``#`` heading becomes the section title for the preamble.
    """
    sections: list[Section] = []
    current_title = default_title
    buffer: list[str] = []
    saw_h1 = False

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append(Section(title=current_title, body=body, lines=list(buffer)))

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        match = _HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            heading = match.group(2).strip()
            if level == 1 and not saw_h1:
                # The H1 is the document title, not a section of its own.
                saw_h1 = True
                current_title = heading
                continue
            flush()
            buffer = []
            current_title = heading
            continue
        buffer.append(line)
    flush()

    if not sections:
        sections = [Section(title=default_title, body=markdown.strip(), lines=markdown.splitlines())]
    return sections


def _split_long_text(text: str, max_tokens: int, overlap_ratio: float) -> list[str]:
    """Window a long section, keeping ~overlap_ratio of context between windows."""
    words = text.split()
    if len(words) <= max_tokens:
        return [text]
    overlap = int(max_tokens * overlap_ratio)
    step = max(1, max_tokens - overlap)
    windows: list[str] = []
    for start in range(0, len(words), step):
        window = words[start : start + max_tokens]
        if not window:
            break
        windows.append(" ".join(window))
        if start + max_tokens >= len(words):
            break
    return windows


def chunk_document(
    doc_id: str,
    title: str,
    text: str,
    access_scope: str = "public",
    updated_at: str = "",
    max_tokens: int | None = None,
    overlap_ratio: float | None = None,
) -> list[Chunk]:
    """Chunk a markdown document into citation-ready pieces."""
    max_tokens = max_tokens or settings.max_chunk_tokens
    overlap_ratio = (
        settings.chunk_overlap_ratio if overlap_ratio is None else overlap_ratio
    )
    sections = split_sections(text, default_title=title)
    chunks: list[Chunk] = []
    chunk_no = 0

    for section in sections:
        body = _WS_RE.sub(" ", section.body).strip()
        if not body:
            continue
        for window in _split_long_text(body, max_tokens, overlap_ratio):
            record_id = stable_record_id(doc_id, chunk_no)
            chunks.append(
                Chunk(
                    record_id=record_id,
                    doc_id=doc_id,
                    chunk_no=chunk_no,
                    title=title,
                    section=section.title,
                    page=section.page,
                    text=window,
                    token_count=count_tokens(window),
                    access_scope=access_scope,
                    content_hash=content_hash(window),
                    updated_at=updated_at,
                )
            )
            chunk_no += 1

    return chunks


def chunk_record_card(
    table: str,
    pk: object,
    text: str,
    title: str,
    access_scope: str = "public",
    updated_at: str = "",
) -> Chunk:
    """Structured rows are indexed as single-chunk 'record cards'.

    The row stays queryable by SQL; the card exists so a row can also be found by
    a natural-language question and cited like any other passage.
    """
    record_id = db_record_id(table, pk)
    return Chunk(
        record_id=record_id,
        doc_id=f"db:{table}",
        chunk_no=0,
        title=title,
        section=table,
        page=None,
        text=text,
        token_count=count_tokens(text),
        access_scope=access_scope,
        content_hash=content_hash(text),
        updated_at=updated_at,
    )


def iter_section_bodies(markdown: str, default_title: str = "Document") -> Iterable[tuple[str, str]]:
    for section in split_sections(markdown, default_title):
        yield section.title, section.body
