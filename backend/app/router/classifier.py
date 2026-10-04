"""Complexity classifier: TF-IDF + logistic regression.

The router needs to know how hard a question is before it decides where to run
it. This is a small, explainable model: a bag of word/character n-grams plus a
handful of structural features (length, numbers, cue counts), trained on labels
derived from the benchmark and the historical query log.

Labels are *derived*, not hand-labelled, so the training set can regrow when the
corpus does. The rule is deliberately conservative and documented in
``label_question``. Reported accuracy is a held-out split; the artefact is saved
so startup does not retrain.
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np

from ..core.schemas import Complexity
from ..core.settings import settings
from ..retrieval.intent import (
    _AGGREGATE_CUES,
    _MULTI_HOP_CUES,
    _POLICY_CUES,
    _RECOMMEND_CUES,
    _SKILL_GAP_CUES,
)

log = logging.getLogger(__name__)

ARTEFACT_NAME = "complexity_clf.pkl"
_ORDER: tuple[Complexity, ...] = (Complexity.low, Complexity.medium, Complexity.high)


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------


def structural_features(question: str) -> list[float]:
    """Cheap, explainable features that do not touch the database."""
    lowered = question.lower()
    words = lowered.split()
    return [
        float(len(question)),
        float(len(words)),
        float(question.count("?")),
        float(sum(1 for ch in question if ch.isdigit())),
        float(sum(1 for token in words if any(c.isdigit() for c in token))),
        float(sum(1 for cue in _MULTI_HOP_CUES if cue in lowered)),
        float(sum(1 for cue in _AGGREGATE_CUES if cue in lowered)),
        float(sum(1 for cue in _POLICY_CUES if cue in lowered)),
        float(sum(1 for cue in _RECOMMEND_CUES if cue in lowered)),
        float(sum(1 for cue in _SKILL_GAP_CUES if cue in lowered)),
        float(lowered.count(",")),
        float(lowered.count(" and ")),
        float(1 if "%" in question else 0),
        float(1 if any(tok in lowered for tok in ("compare", "versus", "vs ")) else 0),
    ]


def _feature_block(questions: Iterable[str]) -> np.ndarray:
    return np.asarray([structural_features(q) for q in questions], dtype=np.float64)


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------


def label_question(question: str, kind: str | None = None) -> Complexity:
    """Derive a complexity label from the question (and its benchmark kind).

    * **high** — multi-hop or comparisons that need more than one source, plus
      adversarial questions that require reasoning about conflicting text.
    * **medium** — policy, placement and aggregated lookups.
    * **low** — single-fact questions (a profile field, a schedule row).
    """
    lowered = question.lower()
    if kind == "multi_hop" or any(cue in lowered for cue in _MULTI_HOP_CUES):
        return Complexity.high
    if kind == "adversarial" and any(cue in lowered for cue in _POLICY_CUES):
        return Complexity.high
    if any(cue in lowered for cue in _AGGREGATE_CUES):
        return Complexity.medium
    if kind in ("policy", "placement"):
        return Complexity.medium
    if any(cue in lowered for cue in _POLICY_CUES):
        return Complexity.medium
    if any(cue in lowered for cue in _RECOMMEND_CUES):
        return Complexity.medium
    if any(cue in lowered for cue in _SKILL_GAP_CUES):
        return Complexity.medium
    return Complexity.low


def build_training_set() -> tuple[list[str], list[str]]:
    """Questions and labels from the benchmark and the historical query log."""
    from ..eval.benchmark import load_benchmark, load_query_history

    questions: list[str] = []
    labels: list[str] = []
    for item in load_benchmark():
        questions.append(item.question)
        labels.append(label_question(item.question, item.kind).value)
    for question in load_query_history():
        questions.append(question)
        labels.append(label_question(question).value)
    return questions, labels


# --------------------------------------------------------------------------
# The classifier
# --------------------------------------------------------------------------


@dataclass
class TrainingReport:
    samples: int
    accuracy: float
    macro_f1: float
    per_class: dict[str, float]

    def as_dict(self) -> dict:
        return {
            "samples": self.samples,
            "accuracy": round(self.accuracy, 4),
            "macro_f1": round(self.macro_f1, 4),
            "per_class_f1": {k: round(v, 4) for k, v in self.per_class.items()},
        }


class ComplexityClassifier:
    """Predicts low / medium / high, with a rule-based fallback shape."""

    def __init__(self, model=None, report: TrainingReport | None = None) -> None:
        self.model = model
        self.report = report

    # --- lifecycle ------------------------------------------------------

    @classmethod
    def artefact_path(cls) -> Path:
        return settings.artifacts_dir / ARTEFACT_NAME

    @classmethod
    def load_or_train(cls) -> "ComplexityClassifier":
        path = cls.artefact_path()
        if path.exists():
            try:
                with path.open("rb") as fh:
                    payload = pickle.load(fh)
                return cls(model=payload["model"], report=payload.get("report"))
            except Exception as exc:  # pragma: no cover - corrupt artefact
                log.warning("could not load %s (%s); retraining", path, exc)
        try:
            return cls.train(save=True)
        except Exception as exc:  # pragma: no cover - no training data yet
            log.warning("complexity classifier could not be trained (%s); using rules", exc)
            return cls(model=None)

    @classmethod
    def train(cls, save: bool = True) -> "ComplexityClassifier":
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.model_selection import train_test_split
        from sklearn.pipeline import FeatureUnion, Pipeline
        from sklearn.preprocessing import FunctionTransformer

        questions, labels = build_training_set()
        if len(questions) < 30:
            raise RuntimeError("not enough labelled questions to train")

        union = FeatureUnion(
            [
                ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
                ("struct", FunctionTransformer(_feature_block, validate=False)),
            ]
        )
        pipeline = Pipeline(
            [
                ("features", union),
                (
                    "clf",
                    LogisticRegression(
                        max_iter=2000, C=4.0, class_weight="balanced", n_jobs=None
                    ),
                ),
            ]
        )

        # Keep the split deterministic and stratified where possible.
        stratify = labels if min(labels.count(v) for v in set(labels)) >= 2 else None
        x_train, x_test, y_train, y_test = train_test_split(
            questions, labels, test_size=0.25, random_state=42, stratify=stratify
        )
        pipeline.fit(x_train, y_train)
        predicted = pipeline.predict(x_test)
        report = TrainingReport(
            samples=len(questions),
            accuracy=float(accuracy_score(y_test, predicted)),
            macro_f1=float(f1_score(y_test, predicted, average="macro")),
            per_class=dict(
                zip(
                    sorted(set(y_test)),
                    f1_score(y_test, predicted, average=None, labels=sorted(set(y_test))),
                )
            ),
        )
        classifier = cls(model=pipeline, report=report)

        if save:
            path = cls.artefact_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as fh:
                pickle.dump(
                    {
                        "model": pipeline,
                        "report": report,
                        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "version": 1,
                    },
                    fh,
                )
        return classifier

    # --- prediction -----------------------------------------------------

    @property
    def available(self) -> bool:
        return self.model is not None

    def predict(self, question: str) -> Complexity:
        if self.model is None:
            return label_question(question)
        try:
            return Complexity(self.model.predict([question])[0])
        except Exception:  # pragma: no cover - model failure must not break routing
            return label_question(question)

    def confidence(self, question: str) -> float:
        if self.model is None:
            return 0.5
        try:
            probabilities = self.model.predict_proba([question])[0]
            return float(max(probabilities))
        except Exception:  # pragma: no cover
            return 0.5

    def classify(
        self, question: str, hint: Complexity | None = None
    ) -> tuple[Complexity, float, str]:
        """Return (complexity, confidence, one-line reason)."""
        if hint is not None:
            return hint, 1.0, "complexity_hint supplied by the caller"
        complexity = self.predict(question)
        confidence = self.confidence(question)
        source = "trained classifier" if self.available else "rule-based fallback"
        return complexity, confidence, f"{source}: {complexity.value} (p={confidence:.2f})"

    def status_detail(self) -> str:
        if self.model is None:
            return "rule-based fallback (no trained artefact)"
        if self.report is None:
            return "trained classifier loaded"
        return (
            f"trained on {self.report.samples} questions, "
            f"accuracy {self.report.accuracy:.2f}, macro-F1 {self.report.macro_f1:.2f}"
        )
