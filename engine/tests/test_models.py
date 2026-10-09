"""Model contract tests — interface, determinism, no-lookahead, real data.

Spec row "Models": one shared interface; fixed-seed determinism (two
trainings on identical data give byte-identical predictions); training
consumes only rounds strictly before the as-of boundary. The pipeline-built
predictable snapshot pins the contract on small data with known outcomes;
the committed 2020-2024 snapshot proves the full
ingestion -> features -> models path end to end.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from f1engine.features import build_asof_features
from f1engine.ingestion import PinnedDataset, load_snapshot
from f1engine.models import (
    FEATURE_COLUMNS,
    MODEL_IDS,
    MODEL_SEED,
    InsufficientTrainingData,
    ModelNotTrained,
    ModelPrediction,
    PredictionModel,
    UnknownRace,
    create_models,
)

RoundKey = tuple[int, int]

MINI_AS_OF: RoundKey = (2021, 4)  # trains on rounds 1-3, predicts round 4
MINI_DRIVERS = {"test-driver", "test-mate", "test-third"}


def _canonical(prediction: ModelPrediction) -> str:
    """Byte-stable serialization of a prediction for equality checks."""
    return json.dumps(
        prediction.model_dump(by_alias=True), sort_keys=True, separators=(",", ":")
    )


def _train_all(
    dataset: PinnedDataset, as_of: RoundKey
) -> dict[str, PredictionModel]:
    table = build_asof_features(dataset)
    models = create_models()
    for model in models.values():
        model.train(dataset, table, as_of)
    return models


def _truncate_after(dataset: PinnedDataset, target: RoundKey) -> PinnedDataset:
    """Everything outcome-bearing after the target round removed.

    Races stay complete (a future schedule is known in advance); results,
    qualifying, and sprints are cut after the target. Mirrors the feature
    suite's truncation helper — the identity and digest fields are left
    untouched so predictions remain byte-comparable across the two datasets.
    """
    through = lambda rows: tuple(  # noqa: E731
        row for row in rows if (row.season, row.round) <= target
    )
    return dataclasses.replace(
        dataset,
        results=through(dataset.results),
        qualifying=through(dataset.qualifying),
        sprints=through(dataset.sprints),
    )


def test_every_model_satisfies_the_protocol() -> None:
    models = create_models()
    assert set(models) == set(MODEL_IDS)
    for model_id, model in models.items():
        assert isinstance(model, PredictionModel)
        assert model.model_id == model_id


def test_untrained_models_refuse_to_predict() -> None:
    for model in create_models().values():
        with pytest.raises(ModelNotTrained):
            model.predict(2021, 4)


def test_trained_models_refuse_unknown_rounds(
    predictable_snapshot: Path,
) -> None:
    dataset = load_snapshot(predictable_snapshot)
    models = _train_all(dataset, MINI_AS_OF)
    for model in models.values():
        with pytest.raises(UnknownRace):
            model.predict(2021, 99)


def test_interface_contract_per_model(predictable_snapshot: Path) -> None:
    dataset = load_snapshot(predictable_snapshot)
    for model_id, model in _train_all(dataset, MINI_AS_OF).items():
        prediction = model.predict(2021, 4)

        assert prediction.race_id == "fourth-grand-prix"
        assert prediction.model_id == model_id
        assert set(prediction.winner) == MINI_DRIVERS
        assert set(prediction.podium) == MINI_DRIVERS
        assert sum(prediction.winner.values()) == pytest.approx(1.0, abs=1e-9)
        assert all(0.0 <= p <= 1.0 for p in prediction.podium.values())
        assert prediction.generated_at == dataset.provenance.generatedAt
        assert prediction.dataset_digest == dataset.dataset_sha256

        diagnostics = prediction.diagnostics
        assert diagnostics.trained_through_season == 2021
        assert diagnostics.trained_through_round == 4
        if model_id == "m3-form":
            # The heuristic declares its narrower, honest feature list.
            assert diagnostics.seed is None
            assert set(diagnostics.features_used) < set(FEATURE_COLUMNS)
        else:
            assert diagnostics.seed == MODEL_SEED
            assert diagnostics.features_used == FEATURE_COLUMNS


def test_two_trainings_are_byte_identical(predictable_snapshot: Path) -> None:
    dataset = load_snapshot(predictable_snapshot)
    table = build_asof_features(dataset)
    for model_id in MODEL_IDS:
        first = create_models()[model_id]
        second = create_models()[model_id]
        first.train(dataset, table, MINI_AS_OF)
        second.train(dataset, table, MINI_AS_OF)

        assert _canonical(first.predict(2021, 4)) == _canonical(
            second.predict(2021, 4)
        ), f"{model_id} is not byte-identical across retraining"


def test_training_refuses_a_single_class_window(
    predictable_snapshot: Path,
) -> None:
    """A window of rounds 1-2 classifies every driver in the top three —
    podium labels carry a single class, which the estimators refuse."""
    dataset = load_snapshot(predictable_snapshot)
    for model_id in ("m1-gbm", "m2-logit"):
        model = create_models()[model_id]
        with pytest.raises(InsufficientTrainingData):
            model.train(dataset, build_asof_features(dataset), (2021, 2))


def test_predictions_move_with_the_training_window(
    real_snapshot: PinnedDataset,
) -> None:
    """Training on a later boundary changes the same race's prediction for
    the parameterized models — a fitted model frozen against its training
    inputs would be a broken model. m3-form carries no trained state, so the
    inverse holds for it and is pinned here too."""
    table = build_asof_features(real_snapshot)
    through_r1 = _train_all(real_snapshot, (2024, 1))
    through_r9 = create_models()
    for model in through_r9.values():
        model.train(real_snapshot, table, (2024, 9))

    early_r1 = through_r1["m1-gbm"].predict(2024, 1)
    late_r1 = through_r9["m1-gbm"].predict(2024, 1)
    assert early_r1.winner != late_r1.winner, "m1-gbm"
    assert through_r1["m2-logit"].predict(2024, 1).winner != (
        through_r9["m2-logit"].predict(2024, 1).winner
    ), "m2-logit"

    # The heuristic reads as-of features only — no training boundary can
    # legitimately move it (the recorded boundary itself is expected to
    # differ; the distributions must not).
    assert through_r1["m3-form"].predict(2024, 1).winner == (
        through_r9["m3-form"].predict(2024, 1).winner
    ), "m3-form must be training-boundary invariant"


def test_training_uses_only_rounds_before_as_of(
    real_snapshot: PinnedDataset,
) -> None:
    """Removing every round after the target changes nothing: training never
    sees labels at or after the as-of boundary (the model-side half of the
    no-lookahead proof; the feature-side half lives in test_features)."""
    target: RoundKey = (2023, 5)
    truncated = _truncate_after(real_snapshot, target)

    full_models = _train_all(real_snapshot, target)
    truncated_models = _train_all(truncated, target)

    for model_id in MODEL_IDS:
        full = full_models[model_id].predict(*target)
        cut = truncated_models[model_id].predict(*target)
        assert _canonical(full) == _canonical(cut), (
            f"{model_id} changed when future rounds were removed — it must "
            "have been reading them"
        )


def test_models_train_and_predict_on_the_real_snapshot(
    real_snapshot: PinnedDataset,
) -> None:
    """The full path on real data: committed snapshot -> features -> three
    trained models -> a 20-driver 2024 Bahrain prediction, trained through
    2023."""
    models = _train_all(real_snapshot, (2024, 1))
    for model_id, model in models.items():
        prediction = model.predict(2024, 1)

        assert prediction.race_id == "bahrain-grand-prix"
        assert len(prediction.winner) == 20
        assert sum(prediction.winner.values()) == pytest.approx(1.0, abs=1e-9)
        assert prediction.dataset_digest == real_snapshot.dataset_sha256

        # The rolling-form floor is a pure function of committed features —
        # its top pick is pinned as a sanity anchor against silent drift.
        if model_id == "m3-form":
            assert (
                max(prediction.winner, key=prediction.winner.get)
                == "max_verstappen"
            )
