"""Weighted ensemble arbiter with numeric consensus flag.

Contract (spec, engine/f1engine/ensemble): a weighted blend of per-model
winner/podium distributions; consensus.podiumSpread = max pairwise JS
divergence across model podium vectors; flag = OK when spread <=
PODIUM_SPREAD_OK_THRESHOLD, else LOW_CONSENSUS. The flag is advisory —
low-consensus predictions are flagged, never suppressed: the blend always
reflects every model's full contribution, and no model is ever dropped.
This implements the Landing Zone's unused DISAGREEMENT_THRESHOLD as a real
number (LZ research §4c, recommendation 2).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

from pydantic import field_validator

from f1engine.models import ModelId, ModelPrediction
from f1engine.wire import WireModel, winner_sums_to_one

PODIUM_SPREAD_OK_THRESHOLD = 0.15

ConsensusFlag = Literal["OK", "LOW_CONSENSUS"]
ModelWeights = dict[ModelId, float]


class EnsembleError(RuntimeError):
    """Base of the ensemble refusal family (code ENSEMBLE_INVALID)."""

    code = "ENSEMBLE_INVALID"


class EnsembleInvalidInput(EnsembleError):
    """No predictions to arbitrate, or the same model appears twice."""

    code = "ENSEMBLE_INPUT_INVALID"


class EnsembleRaceMismatch(EnsembleError):
    """Predictions disagree on which race or dataset they answer."""

    code = "ENSEMBLE_RACE_MISMATCH"


class EnsembleWeightInvalid(EnsembleError):
    """A model has no weight, a non-positive weight, or the weights are empty."""

    code = "ENSEMBLE_WEIGHT_INVALID"


class EnsembleDistributionInvalid(EnsembleError):
    """A podium vector carries no mass and cannot be compared."""

    code = "ENSEMBLE_DISTRIBUTION_INVALID"


class Consensus(WireModel):
    """Numeric cross-model disagreement on the podium distribution."""

    podium_spread: float
    flag: ConsensusFlag


class EnsembleVerdict(WireModel):
    """The arbitrated ensemble verdict carried on every prediction record."""

    race_id: str
    winner: dict[str, float]  # driver_id -> P(win); sums to 1
    podium: dict[str, float]  # driver_id -> P(top 3)
    consensus: Consensus
    weights_used: dict[ModelId, float]  # normalized weights actually applied

    @field_validator("winner")
    @classmethod
    def _winner_sums_to_one(cls, value: dict[str, float]) -> dict[str, float]:
        return winner_sums_to_one(value)


def arbitrate(
    predictions: Sequence[ModelPrediction], weights: ModelWeights
) -> EnsembleVerdict:
    """Blend per-model distributions into the ensemble verdict + consensus flag.

    Weights need not sum to 1 — they are normalized here, and the verdict
    records the normalized weights actually applied.
    """
    if not predictions:
        raise EnsembleInvalidInput("arbitrate needs at least one model prediction")
    model_ids = [prediction.model_id for prediction in predictions]
    if len(set(model_ids)) != len(model_ids):
        raise EnsembleInvalidInput(f"model predicted twice: {model_ids}")
    race_ids = {prediction.race_id for prediction in predictions}
    digests = {prediction.dataset_digest for prediction in predictions}
    if len(race_ids) > 1 or len(digests) > 1:
        raise EnsembleRaceMismatch(
            f"predictions disagree on race or dataset: races={sorted(race_ids)}, "
            f"dataset digests={sorted(digests)}"
        )

    applied = _normalized_weights(predictions, weights)
    winner = _blend(predictions, applied, "winner")
    podium = _blend(predictions, applied, "podium")
    spread = podium_spread(predictions)
    return EnsembleVerdict(
        race_id=predictions[0].race_id,
        winner=winner,
        podium=podium,
        consensus=Consensus(
            podium_spread=spread,
            flag="OK" if spread <= PODIUM_SPREAD_OK_THRESHOLD else "LOW_CONSENSUS",
        ),
        weights_used=applied,
    )


def podium_spread(predictions: Sequence[ModelPrediction]) -> float:
    """Max pairwise Jensen-Shannon divergence (base 2) across podium vectors.

    Each model's podium vector is first normalized into a distribution over
    drivers — its relative share of the expected podium slots — because raw
    P(top-3) vectors sum to ~3, not 1. A single prediction has no partner to
    disagree with: spread 0.0.
    """
    if len(predictions) < 2:
        return 0.0
    distributions = [_normalized_podium(prediction) for prediction in predictions]
    return max(
        _js_divergence(distributions[i], distributions[j])
        for i in range(len(distributions))
        for j in range(i + 1, len(distributions))
    )


def _normalized_weights(
    predictions: Sequence[ModelPrediction], weights: ModelWeights
) -> dict[ModelId, float]:
    applied: dict[ModelId, float] = {}
    for prediction in predictions:
        weight = weights.get(prediction.model_id)
        if weight is None:
            raise EnsembleWeightInvalid(
                f"no weight given for model {prediction.model_id!r}"
            )
        if weight <= 0.0:
            raise EnsembleWeightInvalid(
                f"weight for {prediction.model_id!r} must be positive, got {weight}"
            )
        applied[prediction.model_id] = weight
    total = sum(applied.values())
    return {model_id: weight / total for model_id, weight in applied.items()}


def _blend(
    predictions: Sequence[ModelPrediction],
    applied: dict[ModelId, float],
    field: Literal["winner", "podium"],
) -> dict[str, float]:
    """Weighted average of the per-model distributions over the union of drivers.

    Every model keeps its full weight in the blend regardless of the
    consensus flag — flagged disagreement never suppresses a model.
    """
    drivers = sorted(
        {driver for prediction in predictions for driver in getattr(prediction, field)}
    )
    return {
        driver: sum(
            applied[prediction.model_id]
            * getattr(prediction, field).get(driver, 0.0)
            for prediction in predictions
        )
        for driver in drivers
    }


def _normalized_podium(prediction: ModelPrediction) -> dict[str, float]:
    total = sum(prediction.podium.values())
    if total <= 0.0:
        raise EnsembleDistributionInvalid(
            f"{prediction.model_id}: podium distribution has no mass"
        )
    return {
        driver: probability / total
        for driver, probability in prediction.podium.items()
    }


def _js_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Jensen-Shannon divergence between two distributions, base 2 (range [0, 1])."""
    midpoint = {
        key: (p.get(key, 0.0) + q.get(key, 0.0)) / 2.0 for key in set(p) | set(q)
    }
    return _entropy(midpoint) - (_entropy(p) + _entropy(q)) / 2.0


def _entropy(distribution: dict[str, float]) -> float:
    """Shannon entropy, base 2; zero-mass outcomes contribute nothing."""
    return -sum(
        probability * math.log2(probability)
        for probability in distribution.values()
        if probability > 0.0
    )
