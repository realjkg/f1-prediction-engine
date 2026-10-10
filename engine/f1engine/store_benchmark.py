"""Walk-forward ML benchmarks trained strictly from the SQLite feature store.

For each scored race, train on strictly earlier rounds; do not tune on the
same season's later outcomes. This is an offline challenger benchmark, never
an automatically promoted or live betting/production forecast.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from f1engine.training_store import FEATURE_NAMES, TrainingSample, training_rows_before


@dataclass(frozen=True)
class SeasonScore:
    model: str
    season: int
    races_scored: int
    winner_hit_rate: float
    mean_brier: float
    top4_recall: float


def _array(samples: list[TrainingSample]) -> np.ndarray:
    return np.asarray(
        [[float(v) if v is not None else np.nan for v in row.values] for row in samples],
        dtype=float,
    )


def _target_samples(
    db: sqlite3.Connection, season: int, round_number: int
) -> list[TrainingSample]:
    cols = ", ".join(FEATURE_NAMES)
    sql = (
        "SELECT season, round, driver_id, " + cols + ", won, podium, top4 "
        "FROM training_samples WHERE season=? AND round=? ORDER BY driver_id"
    )
    return [
        TrainingSample(
            season=row[0], round=row[1], driver_id=row[2],
            values=tuple(row[3:3 + len(FEATURE_NAMES)]),
            won=row[-3], podium=row[-2], top4=row[-1],
        )
        for row in db.execute(sql, (season, round_number))
    ]


def _estimator(method: str):
    if method == "logit":
        return make_pipeline(
            SimpleImputer(strategy="median", keep_empty_features=True),
            StandardScaler(),
            LogisticRegression(max_iter=1000, C=0.5, random_state=2026),
        )
    if method == "gbm":
        return HistGradientBoostingClassifier(
            max_iter=80, max_leaf_nodes=7, min_samples_leaf=12,
            learning_rate=0.05, l2_regularization=1.0, random_state=2026,
        )
    raise ValueError(f"unknown model: {method}")


def _win_normalize(raw: np.ndarray) -> np.ndarray:
    # Independent binary driver probabilities must become one race distribution.
    positive = np.maximum(np.asarray(raw, dtype=float), 1e-9)
    return positive / positive.sum()


def _predict(
    history: list[TrainingSample], target: list[TrainingSample], method: str
) -> tuple[np.ndarray, np.ndarray]:
    if method == "form":
        form = np.asarray(
            [row.values[1] if row.values[1] is not None else 25 for row in target],
            dtype=float,
        )
        strength = 1.0 / (form + 1.0)
        return _win_normalize(strength), strength
    x_train = _array(history)
    x_target = _array(target)
    win_model = _estimator(method)
    top4_model = _estimator(method)
    win_model.fit(x_train, np.asarray([row.won for row in history]))
    top4_model.fit(x_train, np.asarray([row.top4 for row in history]))
    p_win = win_model.predict_proba(x_target)[:, 1]
    p_top4 = top4_model.predict_proba(x_target)[:, 1]
    return _win_normalize(p_win), p_top4


def evaluate_season(
    db: sqlite3.Connection, season: int, *, method: str
) -> SeasonScore:
    """Report honest holdout metrics; no same-round or future-race labels."""
    if method not in {"form", "logit", "gbm"}:
        raise ValueError("unsupported method")
    rounds = [
        row[0] for row in db.execute(
            "SELECT DISTINCT round FROM training_samples "
            "WHERE season=? ORDER BY round", (season,)
        )
    ]
    hits: list[float] = []
    briers: list[float] = []
    top4_recalls: list[float] = []
    for round_number in rounds:
        previous = training_rows_before(db, season, round_number)
        target = _target_samples(db, season, round_number)
        if not target or len(previous) < 50:
            continue
        if method != "form" and (
            len({row.won for row in previous}) < 2
            or len({row.top4 for row in previous}) < 2
        ):
            continue
        win, p_top4 = _predict(previous, target, method)
        actual_win = np.asarray([row.won for row in target])
        actual_top4 = np.asarray([row.top4 for row in target])
        hits.append(float(int(np.argmax(win) == np.argmax(actual_win))))
        briers.append(float(np.sum((win - actual_win) ** 2)))
        picked_top4 = set(np.argsort(-p_top4)[:4].tolist())
        actual_top4_indices = {i for i, row in enumerate(actual_top4) if row}
        if actual_top4_indices:
            top4_recalls.append(
                len(picked_top4 & actual_top4_indices) / len(actual_top4_indices)
            )
    if not hits:
        raise ValueError(f"insufficient chronological data to score season {season}")
    return SeasonScore(
        model=method, season=season, races_scored=len(hits),
        winner_hit_rate=sum(hits) / len(hits),
        mean_brier=sum(briers) / len(briers),
        top4_recall=sum(top4_recalls) / len(top4_recalls),
    )
