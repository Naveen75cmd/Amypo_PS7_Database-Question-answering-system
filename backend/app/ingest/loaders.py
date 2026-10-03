"""File loaders.

Each loader returns ``(title, text)``. PDF text is extracted page by page so a
chunk can carry a real page number. Failures are reported, never silently
swallowed: the caller records them in the ingestion result.
"""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LoadedDoc:
    doc_id: str
    title: str
    text: str
    doc_type: str
    source_path: str
    page_map: list[tuple[int, int, int]] | None = None  # (page, start, end) offsets


def doc_id_for(path: Path) -> str:
    """Stable, human-readable document id derived from the filename."""
    stem = path.stem.lower().replace("_", "-").replace(" ", "-")
    return stem


def _title_from_text(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def load_markdown(path: Path) -> LoadedDoc:
    text = path.read_text(encoding="utf-8", errors="replace")
    return LoadedDoc(
        doc_id=doc_id_for(path),
        title=_title_from_text(text, path.stem.replace("-", " ").title()),
        text=text,
        doc_type="md",
        source_path=str(path),
    )


def load_text(path: Path) -> LoadedDoc:
    text = path.read_text(encoding="utf-8", errors="replace")
    # Treat a plain-text file as markdown so heading logic still applies when the
    # file happens to use '#' prefixes; otherwise it becomes one section.
    return LoadedDoc(
        doc_id=doc_id_for(path),
        title=_title_from_text(text, path.stem.replace("-", " ").title()),
        text=text,
        doc_type="txt",
        source_path=str(path),
    )


def load_pdf(path: Path) -> LoadedDoc:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    page_map: list[tuple[int, int, int]] = []
    cursor = 0
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:  # pragma: no cover - corrupt page
            raise RuntimeError(f"failed to extract page {page_no} of {path.name}: {exc}") from exc
        if not page_text.strip():
            continue
        block = f"## Page {page_no}\n\n{page_text.strip()}\n\n"
        start = cursor
        parts.append(block)
        cursor += len(block)
        page_map.append((page_no, start, cursor))
    text = "".join(parts)
    return LoadedDoc(
        doc_id=doc_id_for(path),
        title=_title_from_text(text, path.stem.replace("-", " ").title()),
        text=text,
        doc_type="pdf",
        source_path=str(path),
        page_map=page_map,
    )


def load_docx(path: Path) -> LoadedDoc:
    import docx

    document = docx.Document(str(path))
    lines: list[str] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name or "").lower()
        if style.startswith("heading"):
            level = "".join(ch for ch in style if ch.isdigit()) or "1"
            lines.append(f"{'#' * int(level)} {text}")
        else:
            lines.append(text)
    text = "\n\n".join(lines)
    return LoadedDoc(
        doc_id=doc_id_for(path),
        title=_title_from_text(text, path.stem.replace("-", " ").title()),
        text=text,
        doc_type="docx",
        source_path=str(path),
    )


def load_csv(path: Path) -> LoadedDoc:
    """Render a CSV as a markdown table so it chunks and embeds sensibly."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)
    if not rows:
        return LoadedDoc(
            doc_id=doc_id_for(path), title=path.stem, text="",
            doc_type="csv", source_path=str(path),
        )
    header = rows[0]
    lines = [f"# {path.stem.replace('-', ' ').title()}", "", "## Data table", ""]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows[1:]:
        padded = list(row) + [""] * (len(header) - len(row))
        lines.append("| " + " | ".join(padded[: len(header)]) + " |")
    text = "\n".join(lines)
    return LoadedDoc(
        doc_id=doc_id_for(path),
        title=_title_from_text(text, path.stem.replace("-", " ").title()),
        text=text,
        doc_type="csv",
        source_path=str(path),
    )


LOADERS = {
    ".md": load_markdown,
    ".markdown": load_markdown,
    ".txt": load_text,
    ".pdf": load_pdf,
    ".docx": load_docx,
    ".csv": load_csv,
}


def load_document(path: Path) -> LoadedDoc:
    loader = LOADERS.get(path.suffix.lower())
    if loader is None:
        raise ValueError(f"unsupported file type: {path.suffix}")
    return loader(path)


def _is_hidden(path: Path) -> bool:
    """True when the file or one of its directories is hidden.

    ``.`` and ``..`` are traversal markers, not hidden names, so they are
    excluded from the check.
    """
    for part in path.parts:
        if part in (os.curdir, os.pardir):
            continue
        if part.startswith("."):
            return True
    return False


def discover_documents(root: Path) -> list[Path]:
    """All loadable files under ``root``, ignoring hidden and generated files."""
    if root.is_file():
        return [root]
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if _is_hidden(path):
            continue
        if path.suffix.lower() in LOADERS:
            found.append(path)
    return found
