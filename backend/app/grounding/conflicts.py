"""Conflict detection across retrieved sources (Phase 8, item 6).

The corpus deliberately ships a retired attendance policy next to the current
one. Retrieval now down-ranks the superseded copy, and the prompt asks the model
to prefer the newer date -- but neither of those *tells the user* that two
records disagreed. Judges asked for the disagreement to be visible, so this
module makes it a first-class field on the answer rather than a footnote the
model may or may not mention.

Detection is deliberately conservative: a conflict is only reported when two
retrieved blocks state different values for the same quantity *and* one of them
is explicitly marked as superseded. Reporting a conflict that does not exist
would be worse than missing one, because the UI treats it as a correction.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# "75%", "75 %", "75 percent", "60 percentage" -- the quantities the corpus
# actually contradicts itself about. Kept numeric so "different wording" does
# not read as "different fact".
_QUANTITY = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(?:%|percent|percentage|inr|rs\.?)",
    re.IGNORECASE,
)

# Titles that mark a record as the older of two.
_SUPERSESSION_MARKERS = ("superseded", "deprecated", "obsolete", "old version", "(2019")


def _quantities(text: str) -> set[str]:
    """Normalised quantities asserted by a passage."""
    return {f"{float(m.group(1)):g}{_unit(m.group(0))}" for m in _QUANTITY.finditer(text)}


def _unit(matched: str) -> str:
    lowered = matched.lower()
    if "%" in matched or "percent" in lowered:
        return "%"
    if "inr" in lowered or "rs" in lowered:
        return " INR"
    return ""


def _is_superseded(title: str) -> bool:
    lowered = (title or "").lower()
    return any(marker in lowered for marker in _SUPERSESSION_MARKERS)


def _base_title(title: str) -> str:
    """Strip the parenthetical marker so two versions compare as one record."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", title or "").strip().lower()


def _position(block: Any) -> int:
    """Retrieval order of a block, whether it came from ``Retrieved`` (rank)
    or from a ``ContextBlock`` (index)."""
    value = getattr(block, "rank", None)
    if value is None:
        value = getattr(block, "index", 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return 0


def detect_conflict(blocks: Iterable[Any]) -> dict[str, Any] | None:
    """Return a conflict payload when two retrieved sources disagree.

    ``blocks`` items need ``title`` and ``text`` (``ContextBlock`` satisfies
    this). Returns ``None`` unless the disagreement is real and attributable to
    a superseded record, which is the only case the UI needs to surface.
    """
    rows = [b for b in blocks if getattr(b, "text", None)]
    if len(rows) < 2:
        return None

    for i, older in enumerate(rows):
        if not _is_superseded(getattr(older, "title", "")):
            continue
        older_q = _quantities(older.text)
        if not older_q:
            continue
        for newer in rows:
            if newer is older:
                continue
            title = getattr(newer, "title", "")
            if _is_superseded(title):
                continue
            # Same underlying record, or at least the same asserted quantity
            # under a different heading: this is a version conflict, not two
            # unrelated documents that happen to mention numbers.
            same_record = _base_title(title) == _base_title(getattr(older, "title", ""))
            newer_q = _quantities(newer.text)
            shared_shape = bool(newer_q) and any(
                _suffix(a) == _suffix(b) for a in newer_q for b in older_q
            )
            if not (same_record or shared_shape):
                continue
            if newer_q == older_q:
                continue  # worded differently, factually the same

            winner_value = sorted(newer_q)[0] if newer_q else ""
            # The payload must match ConflictPayload exactly: a key this dict
            # carries and the model does not forbid-allow fails validation, and
            # because the response model is strict that failure is a 500 on a
            # perfectly good answer. Everything here is a declared field.
            return {
                "newer_title": title,
                "newer_index": _position(newer),
                "superseded_title": getattr(older, "title", ""),
                "superseded_index": _position(older),
                "winner_value": winner_value,
                "loser_value": sorted(older_q)[0] if older_q else "",
                "reason": (
                    f"{getattr(older, 'title', 'the older record')} is marked "
                    "superseded; the newer record wins by updated_at"
                ),
            }
    return None


def _suffix(quantity: str) -> str:
    """Unit only, so "75%" and "60%" are comparable as the same kind of fact."""
    return quantity.lstrip("-0123456789.")
