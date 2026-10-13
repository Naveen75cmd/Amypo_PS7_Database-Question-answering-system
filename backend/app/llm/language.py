"""Language detection for multilingual input (Phase 8, item 10 — experimental).

AMYPO answers in English. The job here is narrower and honest: notice when a
question arrived in Tamil or Hindi, say so, and keep the retrieval keys English
so nothing about access control or scoring changes underneath.

Script-based rather than a model, on purpose. A detectable-script heuristic
needs no download, cannot fail offline, and is what the "local models only"
constraint actually permits at this stage. It is therefore marked experimental
everywhere it surfaces, and it is never allowed to block or rewrite a request:
English input must behave byte-for-byte as it did before this existed.
"""

from __future__ import annotations

import unicodedata

# Experimental marker shown alongside any detected non-English input.
EXPERIMENTAL_NOTE = "Experimental: language detected by script, answered in English."

# Contiguous Unicode blocks. (start, end, code) — Tamil first because the
# project brief names it, Devanagari covers Hindi.
_SCRIPT_BLOCKS: tuple[tuple[int, int, str], ...] = (
    (0x0B80, 0x0BFF, "ta"),  # Tamil
    (0x0900, 0x097F, "hi"),  # Devanagari (Hindi)
    (0x0980, 0x09FF, "bn"),  # Bengali
    (0x0A00, 0x0A7F, "pa"),  # Gurmukhi
    (0x0A80, 0x0AFF, "gu"),  # Gujarati
    (0x0C00, 0x0C7F, "te"),  # Telugu
    (0x0600, 0x06FF, "ar"),  # Arabic
)

# What the UI is expected to offer. Others are still reported, just unlabelled.
SUPPORTED = ("en", "ta", "hi")


def _script_of(char: str) -> str | None:
    code = ord(char)
    for start, end, tag in _SCRIPT_BLOCKS:
        if start <= code <= end:
            return tag
    return None


def detect_language(text: str) -> str:
    """Return a BCP-47-ish tag for ``text``; ``"en"`` unless proven otherwise.

    Defaults to English. A non-Latin script must account for a meaningful share
    of the letters before it wins, so a stray Tamil word inside an English
    question does not flip the whole request into "experimental" territory.
    """
    if not text or not text.strip():
        return "en"

    letters = [ch for ch in text if unicodedata.category(ch).startswith("L")]
    if not letters:
        return "en"  # digits, punctuation, whitespace

    votes: dict[str, int] = {}
    latin = 0
    for ch in letters:
        tag = _script_of(ch)
        if tag:
            votes[tag] = votes.get(tag, 0) + 1
        elif ch.isascii():
            latin += 1

    if not votes:
        return "en"

    top_tag, top_count = max(votes.items(), key=lambda kv: kv[1])
    # Majority of letters must be non-Latin script to claim the input is not
    # English; otherwise treat it as English with an incidental foreign token.
    if top_count > len(letters) / 2:
        return top_tag
    if latin >= top_count:
        return "en"
    return top_tag


def is_multilingual(text: str) -> bool:
    """Whether detection should flag the message as experimental."""
    return detect_language(text) not in ("en", "")


def answer_note(text: str) -> str | None:
    """The UI note to attach, or ``None`` when the input is plain English."""
    if not is_multilingual(text):
        return None
    detected = detect_language(text)
    return f"{EXPERIMENTAL_NOTE} (detected: {detected})"
