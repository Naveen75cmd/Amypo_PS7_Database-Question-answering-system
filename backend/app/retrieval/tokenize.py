"""Tokenization for BM25 and feature extraction.

Campus text is full of identifiers that a naive tokenizer destroys: course
codes (``CS301``), student ids (``S102``), company names with digits, and
percentages. We keep the identifier whole *and* emit its parts, so a query for
``CS301`` matches a chunk that mentions ``CS301``, and a query for ``301``
still has a chance.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[A-Za-z]+\d+[A-Za-z]*|\d+(?:\.\d+)?%?|[A-Za-z]+")

STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those is are was were be been
    being am do does did doing have has had having i me my we our you your he she
    it they them their what which who whom whose when where why how all any both
    each few more most other some such no nor not only own same so too very can
    will just should now of in on at to for with from by about as into over after
    before between under above please tell give show find get
    """.split()
)


def tokenize(text: str, keep_stopwords: bool = False) -> list[str]:
    """Lowercase word/identifier tokens, with identifier splitting."""
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text):
        raw = match.group(0)
        lowered = raw.lower()
        if not keep_stopwords and lowered in STOPWORDS:
            continue
        tokens.append(lowered)
        # Split identifiers so "cs301" also indexes as "cs" and "301".
        if any(ch.isdigit() for ch in raw) and any(ch.isalpha() for ch in raw):
            for part in re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?", raw):
                part_lower = part.lower()
                if part_lower and part_lower != lowered:
                    tokens.append(part_lower)
    return tokens


def tokenize_query(text: str) -> list[str]:
    """Query tokenization keeps stopwords off but preserves identifiers."""
    tokens = tokenize(text)
    # Fall back to a raw split when the query is entirely stopwords, so a query
    # like "what is this" still produces something to match on.
    if not tokens:
        tokens = [w.lower() for w in text.split() if w.strip()]
    return tokens


def extract_numbers(text: str) -> set[str]:
    """Normalized numeric literals, used by the grounding verifier."""
    found: set[str] = set()
    for match in re.finditer(r"\d+(?:[.,]\d+)?%?", text):
        raw = match.group(0).replace(",", "")
        found.add(raw.rstrip("%"))
    return found
