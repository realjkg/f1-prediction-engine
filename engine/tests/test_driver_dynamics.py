"""Skill, experience, and durability signals must stop before the target race."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from f1engine.driver_dynamics import (
    DYNAMICS_FEATURE_NAMES,
    dynamics_feature_index,
    with_dynamics,
)
from f1engine.training_store import build_training_store, training_rows_before


def test_recent_experience_and_classification_are_strictly_prior(
    mini_snapshot: Path, tmp_path: Path
) -> None:
    path = tmp_path / "engine.sqlite"
    build_training_store([mini_snapshot], path, as_of=date(2022, 1, 1))
    with sqlite3.connect(path) as db:
        factors = dynamics_feature_index(db)
        first = factors[(2021, 1, "test-driver")]
        second = factors[(2021, 2, "test-driver")]
        assert len(first) == len(DYNAMICS_FEATURE_NAMES) == 8
        assert first[0] == 0.0
        assert first[2] is None
        assert second[0] == 1.0
        assert second[1] == 1.0
        assert second[2] == pytest.approx(1.0)
        assert second[4] == pytest.approx(1.0)
        assert second[5] is None  # not enough history for trends
        assert second[6] is None
        raw = training_rows_before(db, 2021, 2)
        enriched = with_dynamics(raw, factors)
        assert enriched[0].values[-8:] == first
        assert [(s.won, s.podium, s.top4) for s in enriched] == [
            (s.won, s.podium, s.top4) for s in raw
        ]


def test_target_round_outcomes_cannot_modify_its_dynamics(
    mini_snapshot: Path, tmp_path: Path
) -> None:
    path = tmp_path / "engine.sqlite"
    build_training_store([mini_snapshot], path, as_of=date(2022, 1, 1))
    with sqlite3.connect(path) as db:
        original = dynamics_feature_index(db)
        db.execute(
            "UPDATE results SET position=99, status='Retired' "
            "WHERE season=2021 AND round=2"
        )
        db.execute(
            "UPDATE qualifying SET position=99 WHERE season=2021 AND round=2"
        )
        assert dynamics_feature_index(db) == original
        db.execute(
            "UPDATE results SET status='Engine' "
            "WHERE season=2021 AND round=1 AND driver_id='test-driver'"
        )
        changed = dynamics_feature_index(db)
        assert changed[(2021, 1, "test-driver")] == original[
            (2021, 1, "test-driver")
        ]
        assert changed[(2021, 2, "test-driver")][2] == pytest.approx(0.0)
        assert changed[(2021, 2, "test-driver")] != original[
            (2021, 2, "test-driver")
        ]
