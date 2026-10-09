"""Ensemble contract tests — blend math, consensus flag, typed refusals.

Spec row "Ensemble + ledger": weighted blend of the three models' podium
distributions plus a numeric consensus spread (max pairwise Jensen-Shannon
divergence), flagged OK | LOW_CONSENSUS — the flag is advisory and never
suppresses a model. The disagreement case is constructed by hand so the
threshold behavior is exact, not statistical.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from f1engine.ensemble import (
    PODIUM_SPREAD_OK_THRESHOLD,
    EnsembleInvalidInput,
    EnsembleRaceMismatch,
    EnsembleWeightInvalid,
    arbitrate,
    podium_spread,
)
from f1engine.features import build_asof_features
from f1engine.ingestion import load_snapshot
from f1engine.models import (
    FEATURE_COLUMNS,
    MODEL_SEED,
    ModelDiagnostics,
    ModelPrediction,
    create_models,
)

RACE_ID = "mini-race"
DIGEST = "0" * 64
GENERATED_AT = "2026-10-09T00:00:00Z"
WEIGHTS = {"m1-gbm": 1.0, "m2-logit": 1.0, "m3-form": 1.0}


def _prediction(
    model_id: str,
    winner: dict[str, float],
    podium: dict[str, float],
    race_id: str = RACE_ID,
    dataset_digest: str = DIGEST,
) -> ModelPrediction:
    return ModelPrediction(
        race_id=race_id,
        model_id=model_id,  # type: ignore[arg-type]
        winner=winner,
        podium=podium,
        generated_at=GENERATED_AT,
        dataset_digest=dataset_digest,
        diagnostics=ModelDiagnostics(
            trained_through_season=2021,
            trained_through_round=4,
            features_used=FEATURE_COLUMNS,
            seed=MODEL_SEED,
        ),
    )


def _near_consensus() -> list[ModelPrediction]:
    """Three models with identical winners and near-identical podiums."""
    winner = {"alfa": 0.5, "bravo": 0.3, "charlie": 0.2}
    base_podium = {"alfa": 0.9, "bravo": 0.8, "charlie": 0.7, "delta": 0.6}
    return [
        _prediction(
            model_id,
            dict(winner),
            {k: v + offset * 0.005 for k, v in base_podium.items()},
        )
        for offset, model_id in enumerate(("m1-gbm", "m2-logit", "m3-form"))
    ]


def _constructed_disagreement() -> list[ModelPrediction]:
    """m1 backs alfa, m2 backs bravo, m3 is uniform — no shared verdict."""
    return [
        _prediction(
            "m1-gbm",
            {"alfa": 0.98, "bravo": 0.01, "charlie": 0.01},
            {"alfa": 0.99, "bravo": 0.98, "charlie": 0.02, "delta": 0.01},
        ),
        _prediction(
            "m2-logit",
            {"alfa": 0.01, "bravo": 0.98, "charlie": 0.01},
            {"alfa": 0.02, "bravo": 0.99, "charlie": 0.98, "delta": 0.01},
        ),
        _prediction(
            "m3-form",
            {"alfa": 0.34, "bravo": 0.33, "charlie": 0.33},
            {"alfa": 0.75, "bravo": 0.75, "charlie": 0.75, "delta": 0.75},
        ),
    ]


def test_weighted_blend_math() -> None:
    models = [
        _prediction(
            "m1-gbm",
            {"a": 0.7, "b": 0.2, "c": 0.1, "d": 0.0},
            {"a": 1.0, "b": 0.9, "c": 0.6, "d": 0.5},
        ),
        _prediction(
            "m2-logit",
            {"a": 0.4, "b": 0.6, "c": 0.0, "d": 0.0},
            {"a": 1.0, "b": 0.7, "c": 0.7, "d": 0.6},
        ),
        _prediction(
            "m3-form",
            {"a": 0.6, "b": 0.3, "c": 0.1, "d": 0.0},
            {"a": 1.0, "b": 0.8, "c": 0.7, "d": 0.5},
        ),
    ]
    equal = arbitrate(models, WEIGHTS)
    for driver in "abcd":
        assert equal.winner[driver] == pytest.approx(
            sum(model.winner[driver] for model in models) / len(models),
            abs=1e-12,
        )

    # Weights are normalized, then applied: 0.5 / 0.25 / 0.25.
    weighted = arbitrate(
        models, {"m1-gbm": 2.0, "m2-logit": 1.0, "m3-form": 1.0}
    )
    assert weighted.winner["a"] == pytest.approx(0.6, abs=1e-12)
    assert weighted.weights_used == {
        "m1-gbm": 0.5,
        "m2-logit": 0.25,
        "m3-form": 0.25,
    }
    assert sum(weighted.winner.values()) == pytest.approx(1.0, abs=1e-12)


def test_consensus_is_ok_when_models_agree() -> None:
    verdict = arbitrate(_near_consensus(), WEIGHTS)
    assert verdict.consensus.flag == "OK"
    assert verdict.consensus.podium_spread <= PODIUM_SPREAD_OK_THRESHOLD


def test_constructed_disagreement_flags_low_consensus() -> None:
    predictions = _constructed_disagreement()
    spread = podium_spread(predictions)

    assert spread > PODIUM_SPREAD_OK_THRESHOLD
    verdict = arbitrate(predictions, WEIGHTS)
    assert verdict.consensus.flag == "LOW_CONSENSUS"
    assert verdict.consensus.podium_spread == pytest.approx(spread)

    # The flag is advisory: every model still contributes to the verdict —
    # disagreement is surfaced, never suppressed.
    assert set(verdict.weights_used) == {"m1-gbm", "m2-logit", "m3-form"}
    assert set(verdict.winner) == {"alfa", "bravo", "charlie"}


def test_spread_is_bounded_and_symmetric() -> None:
    predictions = _constructed_disagreement()
    spread = podium_spread(predictions)
    assert 0.0 < spread <= 1.0  # base-2 JS divergence is bounded by 1
    assert podium_spread(list(reversed(predictions))) == pytest.approx(spread)


def test_single_prediction_has_no_one_to_disagree_with() -> None:
    solo = _near_consensus()[0]
    verdict = arbitrate([solo], {"m1-gbm": 1})
    assert podium_spread([solo]) == 0.0
    assert verdict.consensus.flag == "OK"
    assert verdict.winner == pytest.approx(solo.winner)


def test_arbiter_refuses_broken_input() -> None:
    with pytest.raises(EnsembleInvalidInput):
        arbitrate([], WEIGHTS)  # nothing to arbitrate

    predictions = _near_consensus()
    with pytest.raises(EnsembleInvalidInput):
        arbitrate(  # one model, counted twice
            [predictions[0], predictions[0]], WEIGHTS
        )

    straddling = _near_consensus()
    straddling[0] = straddling[0].model_copy(update={"race_id": "other-race"})
    with pytest.raises(EnsembleRaceMismatch):
        arbitrate(straddling, WEIGHTS)  # predictions straddle two races

    forked = _near_consensus()
    forked[1] = forked[1].model_copy(update={"dataset_digest": "1" * 64})
    with pytest.raises(EnsembleRaceMismatch):
        arbitrate(forked, WEIGHTS)  # predictions straddle two datasets

    with pytest.raises(EnsembleWeightInvalid):
        arbitrate(  # a model has no weight
            _near_consensus()[:2], {"m1-gbm": 1.0}
        )

    with pytest.raises(EnsembleWeightInvalid):
        arbitrate(
            _near_consensus(),
            {"m1-gbm": 0.0, "m2-logit": 1.0, "m3-form": 1.0},
        )


def test_trained_models_flow_through_the_arbiter(
    predictable_snapshot: Path,
) -> None:
    """The full mini pipeline: trained models -> arbitrated verdict."""
    dataset = load_snapshot(predictable_snapshot)
    table = build_asof_features(dataset)
    predictions = []
    for model in create_models().values():
        model.train(dataset, table, (2021, 4))
        predictions.append(model.predict(2021, 4))

    verdict = arbitrate(predictions, WEIGHTS)
    assert verdict.race_id == "fourth-grand-prix"
    assert set(verdict.winner) == {"test-driver", "test-mate", "test-third"}
    assert 0.0 <= verdict.consensus.podium_spread <= 1.0
