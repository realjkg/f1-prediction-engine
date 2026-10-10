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

from f1engine.driver_dynamics import dynamics_feature_index, with_dynamics
from f1engine.qualifying_features import qualifying_feature_index, with_qualifying
from f1engine.training_store import FEATURE_NAMES, TrainingSample, training_rows_before


@dataclass(frozen=True)
class SeasonScore:
    model: str
    season: int
    races_scored: int
    winner_hit_rate: float
    mean_brier: float
    top4_recall: float
    mean_winner_log_loss: float
    winner_confidence_ece: float
    feature_mode: str
    pole_winner_hit_rate: float | None
    winner_gain_vs_pole: int | None
    differing_winner_picks_from_pole: int | None


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
    if method == "logit-shrink":
        return make_pipeline(
            SimpleImputer(strategy="median", keep_empty_features=True),
            StandardScaler(),
            LogisticRegression(max_iter=1000, C=0.05, random_state=2026),
        )
    if method in {"gbm-shallow", "gbm-regularized"}:
        if method == "gbm-shallow":
            leaves, leaf, l2, iterations = 4, 24, 8.0, 55
        else:
            leaves, leaf, l2, iterations = 7, 35, 25.0, 55
        return HistGradientBoostingClassifier(
            max_iter=iterations, max_leaf_nodes=leaves,
            min_samples_leaf=leaf, learning_rate=0.05,
            l2_regularization=l2, random_state=2026,
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
    if method == "pole":
        # Immutable fixed-rank baseline, not fitted to outcome labels.
        # The first post-qualifying feature is the observed quali position.
        ranks = np.asarray([row.values[len(FEATURE_NAMES)] for row in target], dtype=float)
        ranks = np.where(np.isfinite(ranks), ranks, 999.0)
        strength = np.exp(-0.6 * np.clip(ranks - 1.0, 0.0, 100.0))
        return _win_normalize(strength), strength
    if method == "form":
        form = np.asarray(
            [row.values[1] if row.values[1] is not None else 25 for row in target],
            dtype=float,
        )
        strength = 1.0 / (form + 1.0)
        return _win_normalize(strength), strength
    x_train = _array(history)
    x_target = _array(target)
    estimator_name = method.removesuffix("-qual").removesuffix("-dyn")
    win_model = _estimator(estimator_name)
    top4_model = _estimator(estimator_name)
    win_model.fit(x_train, np.asarray([row.won for row in history]))
    top4_model.fit(x_train, np.asarray([row.top4 for row in history]))
    p_win = win_model.predict_proba(x_target)[:, 1]
    p_top4 = top4_model.predict_proba(x_target)[:, 1]
    return _win_normalize(p_win), p_top4


def evaluate_season(
    db: sqlite3.Connection, season: int, *, method: str
) -> SeasonScore:
    """Report honest holdout metrics; no same-round or future-race labels."""
    if method not in {
        "form", "logit", "gbm", "logit-qual", "gbm-qual", "pole",
        "gbm-shallow-qual", "gbm-regularized-qual", "logit-shrink-qual",
        "gbm-dyn-qual", "logit-dyn-qual",
    }:
        raise ValueError("unsupported method")
    qualify = method.endswith("-qual") or method == "pole"
    qualifying_index = qualifying_feature_index(db) if qualify else {}
    dynamics_index = dynamics_feature_index(db) if "-dyn-" in method else {}
    rounds = [
        row[0] for row in db.execute(
            "SELECT DISTINCT round FROM training_samples "
            "WHERE season=? ORDER BY round", (season,)
        )
    ]
    hits: list[float] = []
    briers: list[float] = []
    log_losses: list[float] = []
    top_picks: list[tuple[float, float]] = []
    top4_recalls: list[float] = []
    pole_correct: list[int] = []
    differing_from_pole = 0
    for round_number in rounds:
        previous = training_rows_before(db, season, round_number)
        target = _target_samples(db, season, round_number)
        if not target or len(previous) < 50:
            continue
        if qualify:
            # A qualifying-conditional model needs a genuine observed session
            # for the target race. No predictions from race result grid fields.
            seen = sum(
                qualifying_index.get((row.season, row.round, row.driver_id), (None,))[0]
                is not None for row in target
            )
            if seen < 2:
                continue
            previous = with_qualifying(previous, qualifying_index)
            target = with_qualifying(target, qualifying_index)
        if dynamics_index:
            previous = with_dynamics(previous, dynamics_index)
            target = with_dynamics(target, dynamics_index)
        if method != "form" and (
            len({row.won for row in previous}) < 2
            or len({row.top4 for row in previous}) < 2
        ):
            continue
        win, p_top4 = _predict(previous, target, method)
        actual_win = np.asarray([row.won for row in target])
        actual_top4 = np.asarray([row.top4 for row in target])
        picked_idx = int(np.argmax(win))
        correct = float(int(picked_idx == np.argmax(actual_win)))
        hits.append(correct)
        if qualify:
            quali_positions = np.asarray(
                [row.values[len(FEATURE_NAMES)] for row in target], dtype=float
            )
            pole_idx = int(np.nanargmin(quali_positions))
            pole_correct.append(int(actual_win[pole_idx]))
            differing_from_pole += int(picked_idx != pole_idx)
        briers.append(float(np.sum((win - actual_win) ** 2)))
        # Winner log loss is based on the entire race distribution, not 20
        # independent Bernoulli claims. A tiny clip keeps it finite.
        actual_idx = int(np.argmax(actual_win))
        log_losses.append(float(-np.log(np.clip(win[actual_idx], 1e-12, 1.0))))
        top_picks.append((float(win.max()), correct))
        picked_top4 = set(np.argsort(-p_top4)[:4].tolist())
        actual_top4_indices = {i for i, row in enumerate(actual_top4) if row}
        if actual_top4_indices:
            top4_recalls.append(
                len(picked_top4 & actual_top4_indices) / len(actual_top4_indices)
            )
    if not hits:
        raise ValueError(f"insufficient chronological data to score season {season}")
    # Coarse top-pick reliability curve; not a substitute for full
    # multiclass calibration. Keep binning fixed before viewing holdouts.
    calibration_error = 0.0
    for low, high in zip((0.0, 0.2, 0.4, 0.6, 0.8),
                         (0.2, 0.4, 0.6, 0.8, 1.01), strict=True):
        values = [
            (confidence, hit) for confidence, hit in top_picks
            if low <= confidence < high
        ]
        if values:
            calibration_error += len(values) / len(top_picks) * abs(
                sum(conf for conf, _ in values) / len(values)
                - sum(hit for _, hit in values) / len(values)
            )
    return SeasonScore(
        model=method, season=season, races_scored=len(hits),
        winner_hit_rate=sum(hits) / len(hits),
        mean_brier=sum(briers) / len(briers),
        top4_recall=sum(top4_recalls) / len(top4_recalls),
        mean_winner_log_loss=sum(log_losses) / len(log_losses),
        winner_confidence_ece=calibration_error,
        feature_mode="post-qualifying replay; source publication timestamp unverified"
        if qualify else "prior-round historical",
        pole_winner_hit_rate=sum(pole_correct) / len(pole_correct)
        if pole_correct else None,
        winner_gain_vs_pole=int(sum(hits) - sum(pole_correct))
        if pole_correct else None,
        differing_winner_picks_from_pole=differing_from_pole
        if pole_correct else None,
    )
