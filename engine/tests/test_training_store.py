"""Verified snapshots to SQLite training rows with no future leakage."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from f1engine.training_store import build_training_store, training_rows_before


def test_sqlite_materialization_and_point_in_time(mini_snapshot: Path, tmp_path: Path) -> None:
    dest = tmp_path / "training.sqlite"
    counts = build_training_store([mini_snapshot], dest, as_of=date(2022, 1, 1))
    assert counts["datasets"] == 1
    assert counts["races"] == 2
    assert counts["samples"] == 6
    with sqlite3.connect(dest) as db:
        assert db.execute("SELECT value FROM metadata WHERE key='as_of_exclusive'").fetchone() == ("2022-01-01",)
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
        assert a.execute("SELECT * FROM training_samples ORDER BY season, round, driver_id").fetchall() == b.execute("SELECT * FROM training_samples ORDER BY season, round, driver_id").fetchall()
