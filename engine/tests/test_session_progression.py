"""Pre-race qualifying session adaptation uses within-session field gaps."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from f1engine.session_progression import (
    SESSION_FEATURE_NAMES,
    session_progression_index,
    with_session_progression,
)
from f1engine.training_store import build_training_store, training_rows_before


def test_relative_session_gaps_and_adaptation(
    mini_snapshot: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "training.sqlite"
    build_training_store([mini_snapshot], dest, as_of=date(2022, 1, 1))
    with sqlite3.connect(dest) as db:
        indexed = session_progression_index(db)
        assert len(SESSION_FEATURE_NAMES) == 4
        # Source fixture has three ranked Q3 drivers, 1 ms apart.
        assert indexed[(2021, 1, "test-driver")][0] == 0.0
        assert indexed[(2021, 1, "test-driver")][1] == 0.0
        assert indexed[(2021, 1, "test-driver")][2] == 0.0
        assert indexed[(2021, 1, "test-mate")][2] == pytest.approx(0.0)
        history = training_rows_before(db, 2021, 2)
        extended = with_session_progression(history, indexed)
        assert all(
            len(after.values) == len(before.values) + len(SESSION_FEATURE_NAMES)
            for before, after in zip(history, extended, strict=True)
        )
        assert [(r.won, r.top4) for r in extended] == [
            (r.won, r.top4) for r in history
        ]


def test_result_tampering_cannot_change_qualifying_adaptation(
    mini_snapshot: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "training.sqlite"
    build_training_store([mini_snapshot], dest, as_of=date(2022, 1, 1))
    with sqlite3.connect(dest) as db:
        before = session_progression_index(db)
        db.execute("UPDATE results SET position=99, grid=99, status='DNF'")
        assert session_progression_index(db) == before

        db.execute(
            "UPDATE qualifying SET q3_ms=q3_ms + 1000 "
            "WHERE season=2021 AND round=1 AND driver_id='test-mate'"
        )
        after = session_progression_index(db)
        assert after[(2021, 1, "test-mate")] != before[
            (2021, 1, "test-mate")
        ]


def test_missing_q3_cannot_be_invented(
    mini_snapshot: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "training.sqlite"
    build_training_store([mini_snapshot], dest, as_of=date(2022, 1, 1))
    with sqlite3.connect(dest) as db:
        db.execute(
            "UPDATE qualifying SET q3_ms=NULL "
            "WHERE season=2021 AND round=1 AND driver_id='test-third'"
        )
        indexed = session_progression_index(db)
        assert indexed[(2021, 1, "test-third")][2:] == (None, None)
        row = training_rows_before(db, 2021, 2)[0]
        assert with_session_progression([row], {})[0].values[-4:] == (
            None, None, None, None
        )
