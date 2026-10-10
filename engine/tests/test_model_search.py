"""Search controls: cohort equality, pole baseline and no autodeploy."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from f1engine.model_search import CANDIDATES, choose_research_candidate
from f1engine.store_benchmark import SeasonScore, _predict
from f1engine.training_store import TrainingSample


def score(model: str, *, brier: float, races: int = 24) -> SeasonScore:
    return SeasonScore(
        model=model, season=2025, races_scored=races,
        winner_hit_rate=0.5, mean_brier=brier, top4_recall=0.5,
        mean_winner_log_loss=1.1, winner_confidence_ece=0.2,
        feature_mode="retrospective",
        pole_winner_hit_rate=0.5,
        winner_gain_vs_pole=0,
        differing_winner_picks_from_pole=0,
    )


def test_search_selects_only_2025_proper_scoring() -> None:
    candidates = {
        name: score(name, brier=0.6 + i * 0.01)
        for i, name in enumerate(CANDIDATES)
    }
    assert choose_research_candidate(candidates).model == CANDIDATES[0]
    better = dict(candidates)
    better[CANDIDATES[1]] = replace(
        better[CANDIDATES[1]], mean_brier=0.55
    )
    assert choose_research_candidate(better).model == CANDIDATES[1]


def test_search_refuses_incomplete_or_unpaired_cohorts() -> None:
    candidates = {
        name: score(name, brier=0.6 + i * 0.01)
        for i, name in enumerate(CANDIDATES)
    }
    with pytest.raises(ValueError, match="incomplete"):
        choose_research_candidate({CANDIDATES[0]: candidates[CANDIDATES[0]]})
    candidates[CANDIDATES[0]] = replace(candidates[CANDIDATES[0]], races_scored=23)
    with pytest.raises(ValueError, match="mismatched"):
        choose_research_candidate(candidates)


def test_pole_model_uses_only_qualifying_values() -> None:
    rows = [
        TrainingSample(
            season=2025, round=1, driver_id=f"d{i}",
            values=(0., None, None, None, None, None, None, None,
                    float(qpos), None, None),
            won=int(i == 2), podium=int(i < 3), top4=1,
        )
        for i, qpos in enumerate((3, 1, 2))
    ]
    win, top4 = _predict([], rows, "pole")
    assert win.sum() == pytest.approx(1.0)
    assert np.isfinite(win).all()
    assert int(win.argmax()) == 1
    assert int(top4.argmax()) == 1
    # Tampering with the winner label must not change pole probabilities.
    poisoned = [
        replace(row, won=int(i == 0))
        for i, row in enumerate(rows)
    ]
    after, _ = _predict([], poisoned, "pole")
    np.testing.assert_array_equal(win, after)
