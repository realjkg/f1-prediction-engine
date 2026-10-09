"""Model registry — one interface, three models, fixed seeds.

Contract (spec, engine/f1engine/models): m1-gbm (HistGradientBoostingClassifier),
m2-logit (LogisticRegression), and m3-form (rolling-form heuristic) behind the
PredictionModel protocol.

Determinism contract: no wall-clock value enters a prediction. ``generatedAt``
mirrors the pinned snapshot's own provenance timestamp, every other field is a
pure function of the training inputs, and the spec sketch's ``durationMs`` is
deliberately absent (it is wall-clock telemetry — the observability task owns
it) — so two trainings on the same data serialize byte-identically, a property
tested, not assumed.

Training semantics: ``train(dataset, table, as_of)`` fits on every round whose
outcome is already decided — (season, round) lexicographically before
``as_of`` — so a model prepared for the 2024 British GP trains on all of
2020-2023 plus the earlier 2024 rounds. Feature rows are as-of by
construction (features.py), so predicting a round consumes only that round's
strictly-prior features; the prediction record carries the training boundary
in its diagnostics rather than trusting callers to remember it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol, runtime_checkable

from pydantic import field_validator
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from f1engine.features import (
    UNCLASSIFIED_FINISH,
    AsOfFeatureRow,
    FeatureTable,
    RoundKey,
)
from f1engine.ingestion import PinnedDataset
from f1engine.wire import WireModel, winner_sums_to_one

MODEL_IDS: tuple[str, ...] = ("m1-gbm", "m2-logit", "m3-form")
MODEL_SEED = 2026

ModelId = Literal["m1-gbm", "m2-logit", "m3-form"]

# Order must match _feature_vector: the diagnostic list and the matrix
# columns are one definition used two ways.
FEATURE_COLUMNS: tuple[str, ...] = (
    "starts",
    "form_finish_mean",
    "form_finish_mean_all",
    "q_best_ms",
    "q_delta_teammate_ms",
    "q_delta_pole_ms",
    "team_points_mean",
    "track_finish_mean",
)

# The heuristic reads only these; diagnostics must say so honestly.
_FORM_FEATURES: tuple[str, ...] = (
    "form_finish_mean",
    "form_finish_mean_all",
    "q_delta_pole_ms",
)


class ModelNotTrained(RuntimeError):
    """predict() called before train() (code MODEL_NOT_TRAINED)."""

    code = "MODEL_NOT_TRAINED"


class UnknownRace(RuntimeError):
    """No as-of feature rows exist for the requested (season, round) (code RACE_UNKNOWN)."""

    code = "RACE_UNKNOWN"


class InsufficientTrainingData(RuntimeError):
    """The training window holds no rows, or labels of a single class."""

    code = "TRAINING_DATA_INSUFFICIENT"


class ModelDiagnostics(WireModel):
    """What a prediction was built from — the record's self-description."""

    trained_through_season: int
    trained_through_round: int  # labels are strictly before (season, round)
    features_used: tuple[str, ...]
    seed: int | None  # None: the model has no stochastic component


class ModelPrediction(WireModel):
    """One model's prediction for one race — the per-model evidence unit."""

    race_id: str
    model_id: ModelId
    winner: dict[str, float]  # driver_id -> P(win); sums to 1 per model
    podium: dict[str, float]  # driver_id -> P(top 3)
    generated_at: str  # snapshot provenance time — input-derived, never wall-clock
    dataset_digest: str
    diagnostics: ModelDiagnostics

    @field_validator("winner", "podium")
    @classmethod
    def _probabilities_in_range(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("distribution must cover at least one driver")
        for driver_id, probability in value.items():
            if not 0.0 <= probability <= 1.0:
                raise ValueError(
                    f"probability for {driver_id!r} outside [0, 1]: {probability}"
                )
        return value

    @field_validator("winner")
    @classmethod
    def _winner_sums_to_one(cls, value: dict[str, float]) -> dict[str, float]:
        return winner_sums_to_one(value)


@runtime_checkable
class PredictionModel(Protocol):
    """The single interface every model implements."""

    model_id: str

    def train(
        self, dataset: PinnedDataset, table: FeatureTable, as_of: RoundKey
    ) -> None:
        """Fit on labels from rounds strictly before ``as_of``; byte-identical on retrain."""
        ...

    def predict(self, season: int, round_number: int) -> ModelPrediction:
        """Predict one running of a race from its as-of features.

        Race identity is (season, round): race_ids repeat across seasons in
        the pinned snapshot, so a bare race_id cannot name a race.
        """
        ...


@dataclass(frozen=True)
class _TrainingSet:
    rows: tuple[AsOfFeatureRow, ...]
    winner_labels: tuple[int, ...]
    podium_labels: tuple[int, ...]


def _training_set(
    dataset: PinnedDataset, table: FeatureTable, as_of: RoundKey
) -> _TrainingSet:
    """Feature rows and outcome labels for every round strictly before as_of."""
    positions: dict[tuple[int, int, str], int | None] = {
        (row.season, row.round, row.driver_id): row.position
        for row in dataset.results
        if (row.season, row.round) < as_of
    }
    rows: list[AsOfFeatureRow] = []
    winner_labels: list[int] = []
    podium_labels: list[int] = []
    for row in table.rows:
        if (row.season, row.round) >= as_of:
            continue
        position = positions.get((row.season, row.round, row.driver_id))
        if (row.season, row.round, row.driver_id) not in positions:
            continue  # no result row, no label — rows mirror results by construction
        winner_labels.append(1 if position == 1 else 0)
        podium_labels.append(1 if position is not None and position <= 3 else 0)
        rows.append(row)
    return _TrainingSet(
        rows=tuple(rows),
        winner_labels=tuple(winner_labels),
        podium_labels=tuple(podium_labels),
    )


def _require_two_classes(
    model_id: str, target: str, labels: tuple[int, ...]
) -> None:
    if len(set(labels)) < 2:
        raise InsufficientTrainingData(
            f"{model_id}: {target} labels in the training window have a single "
            "class — the training window must contain both outcomes"
        )


def _feature_vector(row: AsOfFeatureRow) -> list[float]:
    """The FEATURE_COLUMNS vector for one row; missing values become NaN."""
    return [
        float(value) if value is not None else math.nan
        for value in (
            row.starts,
            row.form_finish_mean,
            row.form_finish_mean_all,
            row.q_best_ms,
            row.q_delta_teammate_ms,
            row.q_delta_pole_ms,
            row.team_points_mean,
            row.track_finish_mean,
        )
    ]


def _rows_by_round(
    table: FeatureTable,
) -> dict[RoundKey, tuple[AsOfFeatureRow, ...]]:
    """Group as-of rows by round, driver-sorted so output ordering is stable."""
    by_round: dict[RoundKey, list[AsOfFeatureRow]] = {}
    for row in table.rows:
        by_round.setdefault((row.season, row.round), []).append(row)
    return {
        key: tuple(sorted(rows, key=lambda row: row.driver_id))
        for key, rows in by_round.items()
    }


class _TwoTargetModel:
    """Shared plumbing for the estimator-backed models.

    Each model fits two classifiers on the same feature matrix — one for the
    winner label, one for the podium label. Subclasses supply fresh
    estimators; training-set assembly, probability shaping, and identity
    recording live here once so the three implementations cannot drift.
    """

    model_id: ClassVar[str]

    def __init__(self) -> None:
        self._winner_clf: object | None = None
        self._podium_clf: object | None = None
        self._dataset: PinnedDataset | None = None
        self._as_of: RoundKey | None = None
        self._rows_by_round: dict[RoundKey, tuple[AsOfFeatureRow, ...]] = {}

    def _estimators(self) -> tuple[object, object]:
        """Two fresh, fixed-seed sklearn classifiers: (winner, podium)."""
        raise NotImplementedError

    def train(
        self, dataset: PinnedDataset, table: FeatureTable, as_of: RoundKey
    ) -> None:
        training = _training_set(dataset, table, as_of)
        if not training.rows:
            raise InsufficientTrainingData(
                f"{self.model_id}: no labeled rounds before (season={as_of[0]}, "
                f"round={as_of[1]}) — nothing to fit"
            )
        _require_two_classes(self.model_id, "winner", training.winner_labels)
        _require_two_classes(self.model_id, "podium", training.podium_labels)

        winner_clf, podium_clf = self._estimators()
        matrix = [_feature_vector(row) for row in training.rows]
        winner_clf.fit(matrix, list(training.winner_labels))
        podium_clf.fit(matrix, list(training.podium_labels))

        self._winner_clf = winner_clf
        self._podium_clf = podium_clf
        self._dataset = dataset
        self._as_of = as_of
        self._rows_by_round = _rows_by_round(table)

    def predict(self, season: int, round_number: int) -> ModelPrediction:
        if self._winner_clf is None or self._podium_clf is None:
            raise ModelNotTrained(
                f"{self.model_id} predicts only after train()"
            )
        rows = self._rows_by_round.get((season, round_number))
        if rows is None or self._dataset is None or self._as_of is None:
            raise UnknownRace(
                f"no as-of feature rows for (season={season}, round={round_number})"
            )
        matrix = [_feature_vector(row) for row in rows]
        winner = _winner_distribution(rows, self._proba(self._winner_clf, matrix))
        podium = {
            row.driver_id: probability
            for row, probability in zip(
                rows, self._proba(self._podium_clf, matrix), strict=True
            )
        }
        return self._record(rows[0].race_id, winner, podium)

    @staticmethod
    def _proba(clf: object, matrix: list[list[float]]) -> list[float]:
        """P(label=1) per row from a fitted two-class classifier."""
        return [
            float(row[1]) for row in clf.predict_proba(matrix)  # type: ignore[attr-defined]
        ]

    def _record(
        self, race_id: str, winner: dict[str, float], podium: dict[str, float]
    ) -> ModelPrediction:
        assert self._dataset is not None and self._as_of is not None  # predict() guards
        return ModelPrediction(
            race_id=race_id,
            model_id=self.model_id,  # type: ignore[arg-type]
            winner=winner,
            podium=podium,
            generated_at=self._dataset.provenance.generatedAt,
            dataset_digest=self._dataset.dataset_sha256,
            diagnostics=ModelDiagnostics(
                trained_through_season=self._as_of[0],
                trained_through_round=self._as_of[1],
                features_used=FEATURE_COLUMNS,
                seed=MODEL_SEED,
            ),
        )


def _winner_distribution(
    rows: Sequence[AsOfFeatureRow], probabilities: Sequence[float]
) -> dict[str, float]:
    """Normalize raw P(win) over the field so the distribution sums to 1.

    The two-class training guard above guarantees a positive total: a fitted
    classifier never emits zero probability for every driver in a field.
    """
    total = sum(probabilities)
    return {
        row.driver_id: probability / total
        for row, probability in zip(rows, probabilities, strict=True)
    }


class GradientBoostingModel(_TwoTargetModel):
    """m1-gbm — gradient-boosted trees on the as-of features.

    HistGradientBoostingClassifier treats NaN features natively (missing
    form/qualifying values send the sample down the learned missing branch),
    so no imputation touches the matrix. Fixed random_state: retraining is
    byte-identical, which the determinism test enforces.
    """

    model_id = "m1-gbm"

    def _estimators(self) -> tuple[object, object]:
        return (
            HistGradientBoostingClassifier(random_state=MODEL_SEED),
            HistGradientBoostingClassifier(random_state=MODEL_SEED),
        )


class LogisticModel(_TwoTargetModel):
    """m2-logit — logistic regression on the same features.

    The interpretable counterweight: medians imputed from the training
    window only, standardized features, and a fixed random_state.
    """

    model_id = "m2-logit"

    def _estimators(self) -> tuple[object, object]:
        def new_pipeline() -> Pipeline:
            return Pipeline(
                [
                    ("impute", SimpleImputer(strategy="median")),
                    ("scale", StandardScaler()),
                    (
                        "logit",
                        LogisticRegression(random_state=MODEL_SEED, max_iter=1000),
                    ),
                ]
            )

        return (new_pipeline(), new_pipeline())


class RollingFormModel:
    """m3-form — deterministic rolling-form heuristic, no estimator.

    Scores each driver by effective mean finish (recent-window form, falling
    back to all-time form; no form data earns no credit) plus a small
    finish-equivalent penalty for a mean qualifying gap to pole. Winner
    probabilities are a softmax over those scores; podium probabilities
    allocate the expected three podium slots by form share, clipped to 1 —
    a sanity floor, not a calibrated model.
    """

    model_id = "m3-form"

    # Mean ms gap to pole converted to finish positions: 100 ms ≈ 0.1 places.
    POLE_GAP_PENALTY_SCALE = 1000.0

    def __init__(self) -> None:
        self._dataset: PinnedDataset | None = None
        self._as_of: RoundKey | None = None
        self._rows_by_round: dict[RoundKey, tuple[AsOfFeatureRow, ...]] = {}

    def train(
        self, dataset: PinnedDataset, table: FeatureTable, as_of: RoundKey
    ) -> None:
        # Nothing to fit — the heuristic reads as-of features directly.
        # train() still records identity so predictions carry provenance.
        self._dataset = dataset
        self._as_of = as_of
        self._rows_by_round = _rows_by_round(table)

    def predict(self, season: int, round_number: int) -> ModelPrediction:
        if self._dataset is None or self._as_of is None:
            raise ModelNotTrained(f"{self.model_id} predicts only after train()")
        rows = self._rows_by_round.get((season, round_number))
        if rows is None:
            raise UnknownRace(
                f"no as-of feature rows for (season={season}, round={round_number})"
            )

        scores = [_form_score(row) for row in rows]
        best = min(scores)
        weights = [math.exp(-(score - best)) for score in scores]
        total = sum(weights)
        winner = {
            row.driver_id: weight / total
            for row, weight in zip(rows, weights, strict=True)
        }
        podium = {
            row.driver_id: min(1.0, 3.0 * weight / total)
            for row, weight in zip(rows, weights, strict=True)
        }
        assert self._dataset is not None and self._as_of is not None  # guarded above
        return ModelPrediction(
            race_id=rows[0].race_id,
            model_id=self.model_id,
            winner=winner,
            podium=podium,
            generated_at=self._dataset.provenance.generatedAt,
            dataset_digest=self._dataset.dataset_sha256,
            diagnostics=ModelDiagnostics(
                trained_through_season=self._as_of[0],
                trained_through_round=self._as_of[1],
                features_used=_FORM_FEATURES,
                seed=None,
            ),
        )


def _form_score(row: AsOfFeatureRow) -> float:
    """Finish-equivalent score; lower is better."""
    if row.form_finish_mean is not None:
        finish = row.form_finish_mean
    elif row.form_finish_mean_all is not None:
        finish = row.form_finish_mean_all
    else:
        finish = UNCLASSIFIED_FINISH  # no form data: no credit
    gap = (
        row.q_delta_pole_ms / RollingFormModel.POLE_GAP_PENALTY_SCALE
        if row.q_delta_pole_ms is not None
        else 0.0
    )
    return finish + gap


def create_models() -> dict[str, PredictionModel]:
    """Fresh model instances keyed by id, in MODEL_IDS order."""
    return {
        "m1-gbm": GradientBoostingModel(),
        "m2-logit": LogisticModel(),
        "m3-form": RollingFormModel(),
    }
