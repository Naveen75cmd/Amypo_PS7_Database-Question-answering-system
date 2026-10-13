"""CLI: ``python -m app.ingest --path ../data/raw``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..core.logging import configure_logging
from ..core.settings import settings
from ..db import get_connection
from .pipeline import corpus_stats, ingest_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest documents and structured data")
    parser.add_argument("--path", default=str(settings.raw_dir),
                        help="directory of documents (default: data/raw)")
    parser.add_argument("--structured", default=str(settings.synthetic_dir),
                        help="directory of structured CSVs (default: data/synthetic)")
    parser.add_argument("--force", action="store_true", help="re-index unchanged documents")
    parser.add_argument("--no-warm", action="store_true",
                        help="skip pre-warming the cache from the query log")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    configure_logging(settings.log_level)
    get_connection()  # ensures migrations ran

    result = ingest_all(
        path=Path(args.path),
        structured_dir=Path(args.structured),
        force=args.force,
        warm=not args.no_warm,
    )
    stats = corpus_stats()

    payload = {
        "documents_changed": result.documents,
        "chunks_written": result.chunks,
        "records_written": result.records,
        "skipped_unchanged": result.skipped_unchanged,
        "duration_ms": result.duration_ms,
        "warmed": result.warmed,
        "errors": result.errors,
        "corpus": stats,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"documents changed : {result.documents}")
        print(f"chunks written    : {result.chunks}")
        print(f"records written   : {result.records}")
        print(f"skipped unchanged : {result.skipped_unchanged}")
        print(f"cache pre-warmed  : {result.warmed} historical questions")
        print(f"duration          : {result.duration_ms:.0f} ms")
        print(f"corpus            : {stats['documents']} documents, "
              f"{stats['chunks']} chunks ({stats['record_cards']} record cards), "
              f"{stats['embedded']} embedded")
        if result.errors:
            print(f"errors ({len(result.errors)}):")
            for err in result.errors[:20]:
                print(f"  - {err}")

    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())
