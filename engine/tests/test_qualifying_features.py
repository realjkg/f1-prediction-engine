"""Same-race qualifying signals without outcome, grid, or future leakage."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from f1engine.qualifying_features import qualifying_feature_index, with_qualifying
from f1engine.training_store import build_training_store, training_rows_before


def test_qualifying_positions_and_q3_time_gaps(mini_snapshot: Path, tmp_path: Path) -> None:
    output = tmp_path / "store.sqlite"
    build_training_store([mini_snapshot], output, as_of=date(2022, 1, 1))
    with sqlite3.connect(output) as db:
        features = qualifying_feature_index(db)
        assert features[(2021, 1, "test-driver")] == (1.0, 0.0, -1.0)
        assert features[(2021, 1, "test-mate")] == (2.0, 1.0, 1.0)
        assert features[(2021, 1, "test-third")] == (3.0, 2.0, 2.0)

        prior = training_rows_before(db, 2021, 2)
        enriched = with_qualifying(prior, features)
        assert len(enriched[0].values) == len(prior[0].values) + 3
        assert [(s.won, s.top4) for s in enriched] == [
            (s.won, s.top4) for s in prior
        ]


def test_frozen_qualifying_does_not_read_classified_results(
    mini_snapshot: Path, tmp_path: Path
) -> None:
    output = tmp_path / "store.sqlite"
    build_training_store([mini_snapshot], output, as_of=date(2022, 1, 1))
    with sqlite3.connect(output) as db:
        original = qualifying_feature_index(db)
        # Deliberately poison classified positions and actual race-start grids.
        db.execute("UPDATE results SET grid=99, position=99")
        assert qualifying_feature_index(db) == original
        # Only observed qualifying inputs are allowed to alter these features.
        db.execute(
            "UPDATE qualifying SET position=7 "
            "WHERE season=2021 AND round=1 AND driver_id='test-driver'"
        )
        changed = qualifying_feature_index(db)
        assert changed[(2021, 1, "test-driver")][0] == 7.0
        assert changed[(2021, 1, "test-driver")][1:] == original[
            (2021, 1, "test-driver")
        ][1:]


def test_missing_session_is_missing_not_invented(
    mini_snapshot: Path, tmp_path: Path
) -> None:
    output = tmp_path / "store.sqlite"
    build_training_store([mini_snapshot], output, as_of=date(2022, 1, 1))
    with sqlite3.connect(output) as db:
        db.execute("DELETE FROM qualifying WHERE season=2021 AND round=2")
        features = qualifying_feature_index(db)
        assert (2021, 2, "test-driver") not in features
        row = training_rows_before(db, 2021, 2)[0]
        absent = with_qualifying([row], {})[0]
        assert absent.values[-3:] == (None, None, None)


def test_challenger_fails_closed_without_scoreable_history(
    mini_snapshot: Path, tmp_path: Path
) -> None:
    from f1engine.store_benchmark import evaluate_season

    output = tmp_path / "store.sqlite"
    build_training_store([mini_snapshot], output, as_of=date(2022, 1, 1))
    with sqlite3.connect(output) as db:
        for method in ("logit-qual", "gbm-qual"):
            with pytest.raises(ValueError, match="insufficient chronological"):
                evaluate_season(db, 2021, method=method)
