"""Claim-level grounding verification.

Three independent checks per claim, because each catches a different failure:

* **Lexical support** — does the claim's content overlap the cited evidence?
  Catches invented facts.
* **Numeric consistency** — does every number in the claim appear in the cited
  evidence? Catches the most damaging failure mode for a data system: a real
  policy quoted with the wrong threshold.
* **Embedding similarity** — is the claim semantically close to the evidence?
  Catches paraphrase drift that lexical overlap alone can miss.

A claim is supported only if it passes the lexical/numeric checks. A number that
is absent from the evidence is a hard failure regardless of how similar the rest
of the sentence is.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..core.settings import settings
from ..retrieval.tokenize import extract_numbers, tokenize_query
from .injection import is_injection

log = logging.getLogger(__name__)

# Sentence splitting that keeps decimal numbers and abbreviations intact.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_MARKER_RE = re.compile(r"\[S(\d+)\]")
_ABSTENTION_RE = re.compile(r"could not find this in AMYPO", re.IGNORECASE)


@dataclass
class Claim:
    text: str
    supported: bool
    score: float
    cited_markers: list[int] = field(default_factory=list)
    evidence_record_id: str | None = None
    evidence_snippet: str | None = None
    reason: str | None = None
    lexical_score: float = 0.0
    numeric_ok: bool = True
    similarity: float = 0.0
    missing_numbers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "supported": self.supported,
            "score": round(self.score, 4),
            "evidence_record_id": self.evidence_record_id,
            "evidence_snippet": self.evidence_snippet,
            "reason": self.reason,
            "lexical_score": round(self.lexical_score, 4),
            "numeric_ok": self.numeric_ok,
            "similarity": round(self.similarity, 4),
            "missing_numbers": self.missing_numbers,
        }


@dataclass
class GroundingReport:
    claims: list[Claim]
    groundedness: float
    confidence: float
    abstained: bool
    supported_claims: int
    total_claims: int
    numeric_violations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "groundedness": round(self.groundedness, 4),
            "confidence": round(self.confidence, 4),
            "abstained": self.abstained,
            "supported_claims": self.supported_claims,
            "total_claims": self.total_claims,
            "numeric_violations": self.numeric_violations,
            "claims": [c.as_dict() for c in self.claims],
        }

    def summary(self) -> str:
        return f"{self.supported_claims}/{self.total_claims} claims supported"


def split_claims(answer: str) -> list[str]:
    """Split an answer into checkable claims, keeping their citation markers."""
    text = answer.strip()
    if not text:
        return []
    parts = [p.strip() for p in _SENTENCE_RE.split(text) if p.strip()]
    # Merge fragments that are only a citation marker onto the previous claim.
    merged: list[str] = []
    for part in parts:
        if merged and _MARKER_RE.fullmatch(part.strip()):
            merged[-1] = f"{merged[-1]} {part}".strip()
        elif len(part) < 15 and merged:
            merged[-1] = f"{merged[-1]} {part}".strip()
        else:
            merged.append(part)
    return merged


class GroundingVerifier:
    """Checks an answer against the passages it cited."""

    def __init__(self, index=None, embedder=None) -> None:
        self.index = index
        self._embedder = embedder

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = getattr(self.index, "embedder", None)
        return self._embedder

    def verify(
        self,
        answer: str,
        context: list[Any],
        question: str = "",
        evidence_override: dict[int, str] | None = None,
    ) -> GroundingReport:
        """Verify ``answer`` against ``context`` (objects with .index and .text).

        ``evidence_override`` maps a marker index to replacement evidence text,
        which the SQL tool path uses because its evidence is a result row rather
        than a retrieved passage.
        """
        by_marker: dict[int, Any] = {}
        for block in context:
            index = getattr(block, "index", None)
            if index is not None:
                by_marker[int(index)] = block
        if evidence_override:
            for index, text in evidence_override.items():
                by_marker.setdefault(index, _RowEvidence(index, text))

        if _ABSTENTION_RE.search(answer):
            return GroundingReport(
                claims=[], groundedness=1.0, confidence=0.0, abstained=True,
                supported_claims=0, total_claims=0,
            )

        claims = split_claims(answer)
        if not claims:
            return GroundingReport(
                claims=[], groundedness=0.0, confidence=0.0, abstained=True,
                supported_claims=0, total_claims=0,
            )

        verified: list[Claim] = []
        numeric_violations: list[str] = []

        all_blocks = [b for b in by_marker.values()]
        # Only substantive terms count for the relevance gate. Single- and
        # two-character tokens are noise here: without this, the possessive "'s"
        # in "the director's home address" matched the "S" in "tier S" and made
        # an unrelated company card look relevant.
        question_terms = _substantive(tokenize_query(question)) if question else set()

        for claim_text in claims:
            # An instruction copied out of the context is not an answer, no matter
            # how verbatim the copy is. Rejecting it here means a model (or the
            # extractive fallback) that surfaces an injected instruction cannot
            # pass verification as if it had stated a supported fact.
            if is_injection(claim_text):
                verified.append(
                    Claim(
                        text=claim_text,
                        supported=False,
                        score=0.0,
                        reason="instruction-like text from context was not treated as an answer",
                    )
                )
                continue

            # Citation markers are metadata, not content. Leaving them in the
            # text diluted the lexical score ("[S1] [S2]" added four tokens) and
            # could push a well-grounded claim below the support threshold.
            content_text = _MARKER_RE.sub(" ", claim_text)

            markers = [int(m) for m in _MARKER_RE.findall(claim_text)]
            cited_blocks = [by_marker[m] for m in markers if m in by_marker]
            # If the model cited nothing, judge the claim against everything.
            candidate_blocks = cited_blocks or all_blocks
            if not candidate_blocks:
                verified.append(
                    Claim(text=claim_text, supported=False, score=0.0,
                          reason="no evidence available")
                )
                continue

            claim_numbers = extract_numbers(claim_text)
            # Citation markers themselves are not content numbers.
            claim_numbers -= {str(m) for m in markers}

            # An answer must address the question. A grounded-but-unrelated
            # sentence (the extractive fallback returning "Amazon is a Product
            # company" for "What is the director's home address?") shares no
            # content term with the question, so it cannot be the answer no
            # matter how well it is supported by its source.
            claim_terms = _substantive(tokenize_query(content_text))
            if question_terms and not (claim_terms & question_terms):
                verified.append(
                    Claim(
                        text=claim_text,
                        supported=False,
                        score=0.0,
                        cited_markers=[int(m) for m in _MARKER_RE.findall(claim_text)],
                        reason="claim does not address the question",
                    )
                )
                continue

            best_block, lexical, similarity, missing = self._best_support(
                content_text, claim_numbers, candidate_blocks
            )
            miscited = False
            if best_block is None and cited_blocks:
                # The claim may be grounded in a passage the model forgot to cite.
                # Checking the whole evidence set distinguishes "miscited" from
                # "invented", which are very different problems: the first is a
                # citation bug we can repair, the second is a hallucination.
                best_block, lexical, similarity, missing = self._best_support(
                    content_text, claim_numbers, all_blocks
                )
                miscited = best_block is not None

            if best_block is None:
                # Keep the strongest candidate for the snippet, but record the failure.
                fallback = max(
                    candidate_blocks,
                    key=lambda b: self._lexical_score(content_text, self._text_of(b)),
                )
                reason = (
                    f"number(s) {missing} not found in any retrieved passage"
                    if missing else "claim is not supported by any retrieved passage"
                )
                numeric_violations.extend(missing)
                verified.append(
                    Claim(
                        text=claim_text, supported=False, score=0.0,
                        cited_markers=markers,
                        evidence_record_id=self._record_id_of(fallback),
                        evidence_snippet=_snippet(
                            self._text_of(fallback), settings.snippet_max_chars
                        ),
                        reason=reason,
                        numeric_ok=not missing,
                        similarity=0.0,
                        missing_numbers=missing,
                    )
                )
                continue

            reason = None
            if miscited:
                reason = (
                    "citation corrected: the model cited a different passage, but "
                    "this evidence supports the claim"
                )

            verified.append(
                Claim(
                    text=claim_text,
                    supported=True,
                    score=lexical,
                    cited_markers=markers,
                    evidence_record_id=self._record_id_of(best_block),
                    evidence_snippet=_snippet(
                        self._text_of(best_block), settings.snippet_max_chars
                    ),
                    reason=reason,
                    lexical_score=lexical,
                    numeric_ok=True,
                    similarity=similarity,
                    missing_numbers=[],
                )
            )

        supported_count = sum(1 for c in verified if c.supported)
        total = len(verified)
        groundedness = supported_count / total if total else 0.0
        confidence = self._confidence(groundedness, verified, question)
        abstained = confidence < settings.verifier_threshold

        return GroundingReport(
            claims=verified,
            groundedness=round(groundedness, 4),
            confidence=round(confidence, 4),
            abstained=abstained,
            supported_claims=supported_count,
            total_claims=total,
            numeric_violations=sorted(set(numeric_violations)),
        )

    # --- scoring helpers ------------------------------------------------

    def _best_support(
        self, claim_text: str, claim_numbers: set[str], blocks: list[Any]
    ) -> tuple[Any | None, float, float, list[str]]:
        """Find the evidence that best supports a claim, if any.

        Returns ``(best_block_or_None, lexical, similarity, missing_numbers)``.

        Numbers are checked against the **union** of the candidate evidence, not
        against each block separately, because a claim may legitimately combine
        two passages ("75% theory attendance and 80% laboratory attendance" is
        one claim supported by two sources). Lexical and semantic scores take the
        best single block, so the reported evidence is always one real passage.

        Numbers remain the hard constraint: if any number the claim states is
        absent from the evidence, the claim cannot be supported no matter how
        similar the prose is. That is what stops a real policy being quoted with
        the wrong threshold.
        """
        texts = [self._text_of(b) for b in blocks]
        texts = [t for t in texts if t]
        if not texts:
            return None, 0.0, 0.0, list(claim_numbers)

        combined = " ".join(texts)
        missing = [n for n in claim_numbers if not _number_present(n, combined)]

        best_block = max(
            blocks, key=lambda b: self._lexical_score(claim_text, self._text_of(b))
        )
        lexical = self._lexical_score(claim_text, self._text_of(best_block))
        similarity = self._similarity(claim_text, self._text_of(best_block))

        numeric_ok = not missing
        supported = numeric_ok and (
            lexical >= settings.claim_similarity_threshold
            or (lexical >= 0.25 and similarity >= 0.6)
        )
        if not supported:
            return None, lexical, similarity, missing
        return best_block, lexical, similarity, missing

    def _lexical_score(self, claim: str, evidence: str) -> float:
        claim_terms = set(tokenize_query(claim))
        if not claim_terms:
            return 0.0
        evidence_terms = set(tokenize_query(evidence))
        overlap = claim_terms & evidence_terms
        return len(overlap) / len(claim_terms)

    def _similarity(self, claim: str, evidence: str) -> float:
        embedder = self.embedder
        if embedder is None:
            return 0.0
        try:
            vectors = embedder.encode([claim, evidence])
            return float(max(0.0, min(1.0, vectors[0] @ vectors[1])))
        except Exception:  # pragma: no cover - embedder failure
            return 0.0

    @staticmethod
    def _confidence(groundedness: float, claims: list[Claim], question: str) -> float:
        """Blend coverage with the average claim strength.

        Coverage dominates (a single unsupported claim in three is a real
        problem), but a fully supported answer built on a single weak claim
        should not read as certain, so the mean claim score pulls it down.
        """
        if not claims:
            return 0.0
        mean_score = sum(c.score for c in claims) / len(claims)
        numeric_penalty = 0.15 if any(not c.numeric_ok for c in claims) else 0.0
        coverage = groundedness
        confidence = 0.72 * coverage + 0.28 * min(1.0, mean_score * 1.6)
        return max(0.0, min(1.0, confidence - numeric_penalty))

    @staticmethod
    def _text_of(block: Any) -> str:
        """All text the model was shown for this block.

        Includes the title and section, because they are part of the labelled
        context the model is given (e.g. "[S4] record_id=... title=\"CS301 Data
        Structures - Course Manual\""). A claim that names its own source's
        title is grounded, not invented.
        """
        if block is None:
            return ""
        parts = [
            getattr(block, "title", "") or "",
            getattr(block, "section", "") or "",
            getattr(block, "text", "") or "",
        ]
        return " ".join(p for p in parts if p)

    @staticmethod
    def _record_id_of(block: Any) -> str | None:
        if block is None:
            return None
        return getattr(block, "record_id", None)


class _RowEvidence:
    """Adapter so a SQL result row can be used as evidence."""

    def __init__(self, index: int, text: str, record_id: str | None = None) -> None:
        self.index = index
        self.text = text
        self.record_id = record_id


def _number_present(number: str, evidence: str) -> bool:
    """Whether ``number`` appears in ``evidence``, tolerating formatting.

    ``4,00,000`` in the corpus must match a claim of ``400000``, and ``75`` must
    match ``75%``. Comparison is on normalized digit strings.
    """
    normalized_evidence = evidence.replace(",", "").replace(" ", "")
    if number in normalized_evidence:
        return True
    # Integer/decimal equivalence: 7.0 matches 7.
    try:
        value = float(number)
    except ValueError:
        return False
    candidates = re.findall(r"\d+(?:\.\d+)?", normalized_evidence)
    return any(abs(float(c) - value) < 1e-9 for c in candidates)


def _substantive(tokens: list[str]) -> set[str]:
    """Content terms only: drop one- and two-character tokens."""
    return {t for t in tokens if len(t) >= 3}


def _snippet(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip() + "…"
