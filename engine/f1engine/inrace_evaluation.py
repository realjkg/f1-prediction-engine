"""Chronological, paired scoring for proposed live-race winner models.

A lap snapshot does not contain its later result. Results are joined only in
this offline evaluator, never the serving inference path. Group all laps from
one Grand Prix in the same evaluation fold to avoid event contamination.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from f1engine.live_prior import UpdatedScenario
from f1engine.race_simulator import InRaceScenario


@dataclass(frozen=True)
class FrozenEvaluationCase:
    season: int
    race_id: str
    lap: int
    observed_at: datetime
    result_published_at: datetime
    winner_driver_number: int
    initial_prior: Mapping[int, float]
    scenario: InRaceScenario
    combined: UpdatedScenario


@dataclass(frozen=True)
class PairedScore:
    races: int
    checkpoints: int
    winner_hit_rate: float
    mean_multiclass_brier: float
    mean_log_loss: float


def _proper_score(
    probability: Mapping[int, float], winner: int,
) -> tuple[float, float, bool]:
    if not probability or winner not in probability:
        raise ValueError("winner must be among verified evaluated entrants")
    values = list(probability.values())
    if not all(math.isfinite(p) and 0 <= p <= 1 for p in values):
        raise ValueError("non-finite winner distribution")
    if not math.isclose(sum(values), 1.0, abs_tol=1e-7):
        raise ValueError("evaluated winner distribution must sum to one")
    brier = sum((p - (1.0 if k == winner else 0.0)) ** 2
                for k, p in probability.items())
    log_loss = -math.log(max(1e-12, probability[winner]))
    pick = max(probability, key=lambda car: (probability[car], -car))
    return brier, log_loss, pick == winner


def evaluate_frozen_cases(
    cases: list[FrozenEvaluationCase],
) -> dict[str, PairedScore]:
    """Score the same exact checkpoints across baselines without tuning."""
    if not cases:
        raise ValueError("no qualified evaluation cases supplied")
    results: dict[str, list[tuple[float, float, bool]]] = {
        "pre-race": [], "running-order": [],
        "green-continuation": [], "research-combination": [],
    }
    races: set[tuple[int, str]] = set()
    seen: set[tuple[int, str, int]] = set()
    for case in cases:
        key = (case.season, case.race_id, case.lap)
        if key in seen:
            raise ValueError("duplicate checkpoint must not increase accuracy")
        seen.add(key)
        races.add((case.season, case.race_id))
        if (
            case.observed_at.tzinfo is None or case.result_published_at.tzinfo is None
            or case.result_published_at.astimezone(UTC)
            <= case.observed_at.astimezone(UTC)
        ):
            raise ValueError("result timestamp must follow frozen checkpoint")
        scenario, combined = case.scenario, case.combined
        if (
            scenario.season, scenario.race_id, scenario.checkpoint_lap
        ) != (case.season, case.race_id, case.lap):
            raise ValueError("scenario does not match frozen checkpoint")
        if (
            combined.checkpoint_sha256 != scenario.checkpoint_record_sha256
            or combined.lap != case.lap
            or combined.status != "unqualified-blend"
        ):
            raise ValueError("combined scenario references wrong source")
        order = sorted(scenario.drivers, key=lambda item: item.current_position)
        cars = {x.driver_number for x in order}
        if cars != set(case.initial_prior) or cars != {
            x.driver_number for x in combined.candidates
        }:
            raise ValueError("compared models have different entrant fields")
        # Current running order is an explicit one-hot naive baseline.
        lead = order[0].driver_number
        current_order = {car: (1.0 if car == lead else 0.0) for car in cars}
        by_model: dict[str, Mapping[int, float]] = {
            "pre-race": case.initial_prior,
            "running-order": current_order,
            "green-continuation": {
                d.driver_number: d.conditional_win_frequency for d in order
            },
            "research-combination": {
                d.driver_number: d.blended_research_weight for d in combined.candidates
            },
        }
        for label, probability in by_model.items():
            results[label].append(_proper_score(probability, case.winner_driver_number))
    return {
        label: PairedScore(
            races=len(races), checkpoints=len(scores),
            winner_hit_rate=sum(hit for _, _, hit in scores) / len(scores),
            mean_multiclass_brier=sum(b for b, _, _ in scores) / len(scores),
            mean_log_loss=sum(ll for _, ll, _ in scores) / len(scores),
        )
        for label, scores in results.items()
    }
