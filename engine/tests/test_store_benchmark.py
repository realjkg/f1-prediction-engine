"""Guardrails for deterministic SQLite-trained challenger models."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from f1engine.store_benchmark import _win_normalize, evaluate_season
from f1engine.training_store import build_training_store


def test_winner_probabilities_are_a_distribution() -> None:
    p = _win_normalize(np.asarray([0.0, 0.1, 0.4]))
    assert p.sum() == pytest.approx(1.0)
    assert all(p > 0)
    assert int(p.argmax()) == 2


def test_refuse_to_score_small_chronology(mini_snapshot: Path, tmp_path: Path) -> None:
    store = tmp_path / "store.sqlite"
    build_training_store([mini_snapshot], store, as_of=date(2022, 1, 1))
    with sqlite3.connect(store) as db:
        with pytest.raises(ValueError, match="insufficient chronological"):
            evaluate_season(db, 2021, method="gbm")
        with pytest.raises(ValueError, match="unsupported"):
            evaluate_season(db, 2021, method="magic")
