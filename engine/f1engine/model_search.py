"""Reproducible bounded model search; accuracy never overrides provenance.

2025 is a *research-selection* cohort and 2026 a later diagnostic cohort,
not a claim of pristine blindness: both seasons' results have already been
inspected in previous model research. Future unseen races are the real
promotion validation. No model here is auto-deployed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import Any

from f1engine.store_benchmark import SeasonScore, evaluate_season

BASELINE = "pole"
CANDIDATES = (
    "gbm-qual",
    "logit-qual",
    "gbm-shallow-qual",
    "gbm-regularized-qual",
    "logit-shrink-qual",
    "gbm-dyn-qual",
    "logit-dyn-qual",
    "gbm-session-qual",
    "gbm-dyn-session-qual",
)
RESEARCH_SEASON = 2025
DIAGNOSTIC_SEASON = 2026
STRETCH_WINNER_ACCURACY = 0.98


def choose_research_candidate(
    selection_scores: dict[str, SeasonScore],
) -> SeasonScore:
    """Choose on 2025 *only*; never rank candidates by 2026 results."""
    if set(selection_scores) != set(CANDIDATES):
        raise ValueError("incomplete candidate portfolio; do not silently narrow search")
    if len({x.races_scored for x in selection_scores.values()}) != 1:
        raise ValueError("candidates were evaluated on mismatched race cohorts")
    return min(
        selection_scores.values(),
        key=lambda score: (
            score.mean_brier, score.mean_winner_log_loss, score.model
        ),
    )


def search_report(db: sqlite3.Connection) -> dict[str, Any]:
    """Evaluate only a declared portfolio and produce a non-promotable report."""
    all_scores: dict[int, dict[str, SeasonScore]] = {}
    for year in (RESEARCH_SEASON, DIAGNOSTIC_SEASON):
        all_scores[year] = {
            method: evaluate_season(db, year, method=method)
            for method in (BASELINE, *CANDIDATES)
        }
        cohort = all_scores[year]
        if len({v.races_scored for v in cohort.values()}) != 1:
            raise ValueError(f"unequal {year} race coverage, refuses comparison")
    chosen = choose_research_candidate(
        {key: all_scores[RESEARCH_SEASON][key] for key in CANDIDATES}
    )
    pole_2025 = all_scores[RESEARCH_SEASON][BASELINE]
    pole_2026 = all_scores[DIAGNOSTIC_SEASON][BASELINE]
    picked_2026 = all_scores[DIAGNOSTIC_SEASON][chosen.model]

    # A positive uplift against pole plus better proper scoring would only
    # justify investigating promotion, not enabling production inference.
    evidence_quality = (
        chosen.winner_gain_vs_pole is not None
        and chosen.winner_gain_vs_pole > 0
        and chosen.mean_brier < pole_2025.mean_brier
        and chosen.mean_winner_log_loss < pole_2025.mean_winner_log_loss
        and picked_2026.winner_gain_vs_pole is not None
        and picked_2026.winner_gain_vs_pole > 0
        and picked_2026.mean_brier < pole_2026.mean_brier
    )
    return {
        "selection_cohort": "2025 research (already inspected, not pristine blind)",
        "diagnostic_cohort": "2026 available rounds (also previously inspected)",
        "pre_race_timestamp_verified": False,
        "starting_entries_verified_pre_race": False,
        "model_promotion_allowed": False,
        "reason": (
            "Retrospective qualifying source lacks publication timestamps, "
            "verified pre-race entrants, grid penalties, and prospective "
            "confidence calibration; forward-frozen predictions required"
        ),
        "target_metric": "exact Grand Prix winner chosen before lights out",
        "aspirational_winner_hit_rate": STRETCH_WINNER_ACCURACY,
        "pole_uplift_and_proper_scoring_gate_passed": bool(evidence_quality),
        "research_candidate_selected_using_2025_only": chosen.model,
        "per_season": {
            str(year): {
                method: asdict(score)
                for method, score in all_scores[year].items()
            }
            for year in (RESEARCH_SEASON, DIAGNOSTIC_SEASON)
        },
    }
