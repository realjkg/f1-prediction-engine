"""Training-store persistence and point-in-time materialization tests."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from f1engine.backtest import run_backtest
from f1engine.evidence import SkippedRound
from f1engine.training_store import (
    ImmutableRecordConflict,
    TrainingStore,
    build_training_store,
    training_rows_before,
)


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
        # Preserve scoreable rounds; change only the stored skipped-round count.
        altered = replace(
            backtest,
            skipped=backtest.skipped + (
                SkippedRound(
                    season=2021, round=99,
                    code="TRAINING_DATA_INSUFFICIENT",
                    message="synthetic revision-conflict probe",
                ),
            ),
        )
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


def test_sqlite_materialization_and_point_in_time(mini_snapshot: Path, tmp_path: Path) -> None:
    dest = tmp_path / "training.sqlite"
    counts = build_training_store([mini_snapshot], dest, as_of=date(2022, 1, 1))
    assert counts["datasets"] == 1
    assert counts["races"] == 2
    assert counts["samples"] == 6
    with sqlite3.connect(dest) as db:
        value = db.execute(
            "SELECT value FROM metadata WHERE key='as_of_exclusive'"
        ).fetchone()
        assert value == ("2022-01-01",)
        assert db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 6
        assert len(training_rows_before(db, 2021, 1)) == 0
        prior = training_rows_before(db, 2021, 2)
        assert len(prior) == 3
        assert all((s.season, s.round) == (2021, 1) for s in prior)
        assert sum(s.won for s in prior) == 1
        assert len(prior[0].values) == 8


def test_refuses_outcomes_on_or_after_cutoff(mini_snapshot: Path, tmp_path: Path) -> None:
    dest = tmp_path / "training.sqlite"
    with pytest.raises(ValueError, match="cutoff"):
        build_training_store([mini_snapshot], dest, as_of=date(2021, 5, 30))
    assert not dest.exists()


def test_refuses_duplicate_seasons(mini_snapshot: Path, tmp_path: Path) -> None:
    dest = tmp_path / "training.sqlite"
    with pytest.raises(ValueError, match="overlapping"):
        build_training_store([mini_snapshot, mini_snapshot], dest, as_of=date(2022, 1, 1))
    assert not dest.exists()


def test_materialization_is_repeatable(mini_snapshot: Path, tmp_path: Path) -> None:
    first = tmp_path / "a.sqlite"
    second = tmp_path / "b.sqlite"
    for output in (first, second):
        build_training_store([mini_snapshot], output, as_of=date(2022, 1, 1))
    with sqlite3.connect(first) as a, sqlite3.connect(second) as b:
        query = "SELECT * FROM training_samples ORDER BY season, round, driver_id"
        assert a.execute(query).fetchall() == b.execute(query).fetchall()
