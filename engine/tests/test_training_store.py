"""SQLite training evidence tests: immutable data and no future-label access."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from f1engine.backtest import run_backtest
from f1engine.training_store import ImmutableRecordConflict, TrainingStore


def test_dataset_import_is_idempotent_and_persistent(
    predictable_dataset, tmp_path: Path
) -> None:
    target = tmp_path / "training" / "f1.sqlite"
    with TrainingStore(target) as store:
        store.import_dataset(predictable_dataset)
        first = store.inventory()
        store.import_dataset(predictable_dataset)
        assert store.inventory() == first
        assert first["dataset_versions"] == 1
        assert first["races"] == 5
        assert first["feature_rows"] > 0
    with TrainingStore(target) as reopened:
        assert reopened.inventory() == first


def test_prior_round_boundary_does_not_expose_target_or_future_labels(
    predictable_dataset, tmp_path: Path
) -> None:
    with TrainingStore(tmp_path / "training.sqlite") as store:
        store.import_dataset(predictable_dataset)
        past = store.training_examples_before(
            predictable_dataset.dataset_sha256, 2021, 4
        )
        later = store.training_examples_before(
            predictable_dataset.dataset_sha256, 2021, 5
        )
        assert past
        assert all((season, round_number) < (2021, 4)
                   for season, round_number, *_ in past)
        assert all((season, round_number) < (2021, 5)
                   for season, round_number, *_ in later)
        assert len(later) > len(past)


def test_same_digest_cannot_change_provenance(
    predictable_dataset, tmp_path: Path
) -> None:
    with TrainingStore(tmp_path / "training.sqlite") as store:
        store.import_dataset(predictable_dataset)
        modified = replace(predictable_dataset, dataset_id="changed-same-digest")
        with pytest.raises(ImmutableRecordConflict, match="dataset_versions"):
            store.import_dataset(modified)


def test_probabilities_keep_distinct_model_revisions(
    predictable_dataset, tmp_path: Path
) -> None:
    backtest = run_backtest(
        predictable_dataset, target_season=2021,
        weights={"m1-gbm": 1.0, "m2-logit": 1.0, "m3-form": 1.0},
    )
    assert backtest.rounds
    with TrainingStore(tmp_path / "training.sqlite") as store:
        store.import_dataset(predictable_dataset)
        store.record_backtest(predictable_dataset, backtest, "baseline-v1")
        first = store.inventory()
        assert first["probabilities"] > 0
        store.record_backtest(predictable_dataset, backtest, "baseline-v1")
        assert store.inventory() == first
        store.record_backtest(predictable_dataset, backtest, "candidate-v2")
        second = store.inventory()
        assert second["model_runs"] == 2
        assert second["probabilities"] == 2 * first["probabilities"]
        altered = replace(backtest, rounds=())
        with pytest.raises(ImmutableRecordConflict, match="model_runs"):
            store.record_backtest(predictable_dataset, altered, "baseline-v1")


def test_model_revision_must_be_named(
    predictable_dataset, tmp_path: Path
) -> None:
    backtest = run_backtest(
        predictable_dataset, target_season=2021,
        weights={"m1-gbm": 1.0, "m2-logit": 1.0, "m3-form": 1.0},
    )
    with TrainingStore(tmp_path / "training.sqlite") as store:
        store.import_dataset(predictable_dataset)
        with pytest.raises(ValueError, match="model_revision"):
            store.record_backtest(predictable_dataset, backtest, " ")
