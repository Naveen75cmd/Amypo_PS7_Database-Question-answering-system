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
# Bumped when the training recipe changes materially. An artefact from an older
# recipe is retrained on load rather than quietly serving numbers that were
# measured a different way (2 = feedback-weighted training, fixed holdout).
ARTEFACT_VERSION = 2
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


def static_split() -> tuple[list[str], list[str], list[str], list[str]]:
    """Fixed train/holdout split of the *derived* corpus.

    The holdout is carved only from the static corpus, so every retrain is
    scored on exactly the same questions and two accuracy numbers are
    comparable. Feedback examples join training only: a question the model is
    being judged on must never become training data, or the delta would be
    measuring memorisation rather than learning.
    """
    from sklearn.model_selection import train_test_split

    questions, labels = build_training_set()
    stratify = labels if min(labels.count(v) for v in set(labels)) >= 2 else None
    # train_test_split returns (X_train, X_test, y_train, y_test); return them in
    # (x_train, y_train, x_test, y_test) order so callers cannot silently pair
    # questions with the wrong labels.
    x_train, x_test, y_train, y_test = train_test_split(
        questions, labels, test_size=0.25, random_state=42, stratify=stratify
    )
    return x_train, y_train, x_test, y_test


def _harder(complexity: Complexity) -> Complexity:
    """One step up the complexity ladder; ``high`` is already the top."""
    return _ORDER[min(_ORDER.index(complexity) + 1, len(_ORDER) - 1)]


def feedback_examples(
    limit: int | None = None,
) -> tuple[list[str], list[str], dict[str, int]]:
    """Labelled examples from thumbs ratings (Phase 8, item 1).

    A thumbs-up *confirms* the complexity the router assigned to the question,
    so the pair becomes a labelled example. A thumbs-down says the answer was
    not good enough, which for a complexity classifier means the router
    under-rated the question: the example is relabelled one step harder, which
    is the correction the router can actually act on. Both outcomes are counted
    so the dashboard can show how much live signal went into the model.

    Returns ``(questions, labels, {"confirmed", "corrected"})``. An empty log,
    or a database that is not reachable, is not an error: retraining falls back
    to the derived corpus rather than failing.
    """
    from ..db import query

    try:
        rows = query(
            """
            SELECT q.question AS question, d.complexity AS complexity,
                   q.feedback AS feedback
            FROM query_log q
            JOIN router_decisions d ON d.request_id = q.request_id
            WHERE q.feedback IS NOT NULL AND q.question IS NOT NULL
            ORDER BY q.created_at DESC
            LIMIT ?
            """,
            (int(limit if limit is not None else settings.retrain_max_feedback),),
        )
    except Exception as exc:  # pragma: no cover - depends on the live schema
        log.warning("feedback examples unavailable (%s); training on the corpus", exc)
        return [], [], {"confirmed": 0, "corrected": 0}

    questions: list[str] = []
    labels: list[str] = []
    counts = {"confirmed": 0, "corrected": 0}
    for row in rows:
        question = (row.get("question") or "").strip()
        try:
            assigned = Complexity(row.get("complexity"))
        except (TypeError, ValueError):
            continue  # no complexity recorded: nothing to learn from
        if not question:
            continue
        if int(row.get("feedback") or 0) > 0:
            questions.append(question)
            labels.append(assigned.value)
            counts["confirmed"] += 1
        else:
            questions.append(question)
            labels.append(_harder(assigned).value)
            counts["corrected"] += 1
    return questions, labels, counts


# --------------------------------------------------------------------------
# The classifier
# --------------------------------------------------------------------------


@dataclass
class TrainingReport:
    samples: int
    accuracy: float
    macro_f1: float
    per_class: dict[str, float]
    # Added with feedback-driven retraining. Defaulted so a report pickled by an
    # older artefact still loads and still reports its accuracy.
    holdout: int = 0
    from_feedback: int = 0
    confirmed: int = 0
    corrected: int = 0

    def as_dict(self) -> dict:
        return {
            "samples": self.samples,
            "accuracy": round(self.accuracy, 4),
            "macro_f1": round(self.macro_f1, 4),
            "holdout": self.holdout,
            "from_feedback": self.from_feedback,
            "confirmed": self.confirmed,
            "corrected": self.corrected,
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
                if int(payload.get("version", 0)) != ARTEFACT_VERSION:
                    log.info(
                        "artefact %s is version %s, expected %s; retraining",
                        path, payload.get("version"), ARTEFACT_VERSION,
                    )
                    raise ValueError("stale artefact version")
                return cls(model=payload["model"], report=payload.get("report"))
            except Exception as exc:  # pragma: no cover - corrupt/stale artefact
                log.warning("could not load %s (%s); retraining", path, exc)
        try:
            return cls.train(save=True)
        except Exception as exc:  # pragma: no cover - no training data yet
            log.warning("complexity classifier could not be trained (%s); using rules", exc)
            return cls(model=None)

    @classmethod
    def train(
        cls, save: bool = True, use_feedback: bool = True
    ) -> "ComplexityClassifier":
        """Fit the classifier on the derived corpus plus live thumbs feedback.

        Feedback rows are weighted by ``settings.retrain_feedback_weight`` so a
        handful of human verdicts can actually move a corpus of a few hundred
        derived examples, and the reported accuracy is always measured on the
        same fixed holdout so the dashboard delta compares like with like.
        """
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.pipeline import FeatureUnion, Pipeline
        from sklearn.preprocessing import FunctionTransformer

        train_questions, train_labels, holdout_questions, holdout_labels = static_split()
        fb_questions: list[str] = []
        fb_labels: list[str] = []
        counts = {"confirmed": 0, "corrected": 0}
        if use_feedback:
            fb_questions, fb_labels, counts = feedback_examples()

        questions = train_questions + fb_questions
        labels = train_labels + fb_labels
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

        # Only the feedback rows carry weight; the derived examples stay at 1.0
        # so the baseline behaviour is unchanged when there is no feedback yet.
        weights = np.asarray(
            [1.0] * len(train_questions)
            + [settings.retrain_feedback_weight] * len(fb_questions),
            dtype=np.float64,
        )
        pipeline.fit(questions, labels, clf__sample_weight=weights)
        predicted = pipeline.predict(holdout_questions)
        classes = sorted(set(holdout_labels))
        report = TrainingReport(
            samples=len(questions),
            holdout=len(holdout_questions),
            from_feedback=len(fb_questions),
            confirmed=counts["confirmed"],
            corrected=counts["corrected"],
            accuracy=float(accuracy_score(holdout_labels, predicted)),
            macro_f1=float(f1_score(holdout_labels, predicted, average="macro")),
            per_class=dict(
                zip(
                    classes,
                    f1_score(holdout_labels, predicted, average=None, labels=classes),
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
                        "version": ARTEFACT_VERSION,
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
