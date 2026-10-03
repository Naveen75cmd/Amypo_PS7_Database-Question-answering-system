"""CLI: build the retrieval index and run the retrieval ablation.

    python -m app.retrieval            # build + evaluate
    python -m app.retrieval --no-eval  # build only
"""

from __future__ import annotations

import argparse
import sys

from ..core.logging import configure_logging
from ..core.settings import settings
from ..db import get_connection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and evaluate the retrieval index")
    parser.add_argument("--no-eval", action="store_true", help="build the index only")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--modes", nargs="*", default=None,
                        help="subset of: dense bm25 hybrid hybrid_rerank")
    parser.add_argument("--by-kind", action="store_true", help="also print per-kind breakdown")
    args = parser.parse_args(argv)

    configure_logging(settings.log_level)
    get_connection()

    from .index import RetrievalIndex

    index = RetrievalIndex.load_or_build()
    stats = index.stats()
    print(f"index: {stats['chunks']} chunks, dim={stats['dim']}, "
          f"backend={stats['backend']}, embedder={stats['embedder']}")
    if index.is_empty:
        print("index is empty — run: python -m app.ingest", file=sys.stderr)
        return 1

    if args.no_eval:
        return 0

    from ..eval.benchmark import load_benchmark
    from ..eval.retrieval_eval import MODES, evaluate_retrieval, format_by_kind, format_table

    modes = tuple(args.modes) if args.modes else MODES
    items = load_benchmark()
    results = evaluate_retrieval(index, items, modes=modes, top_k=args.top_k)

    print()
    print(format_table(results))
    if args.by_kind:
        print()
        print(format_by_kind(items, index))
    print(f"\nreport: {settings.docs_dir / 'eval' / 'retrieval_latest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
