"""Point-in-time longitudinal driver and constructor features from prior races.

Every driver/constructor statistic is frozen *before* target-round results
are considered. Drivers' abilities and car reliability are only proxies:
incident-caused DNF is not the same as mechanical failure, and neither is
a medically grounded property of a person.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, replace
from statistics import fmean

from f1engine.training_store import TrainingSample

DYNAMICS_FEATURE_NAMES = (
    "driver_prior_starts",
    "driver_season_starts",
    "driver_recent_classified_rate",
    "constructor_recent_classified_rate",
    "driver_recent_top4_rate",
    "driver_finish_improvement",
    "driver_qualifying_improvement",
    "driver_positions_gained_last8",
)

DriverKey = tuple[int, int, str]


@dataclass(frozen=True)
class _PriorRace:
    season: int
    constructor_id: str
    finish: int | None
    qualified: int | None
    classified: bool


def _classified(status: str) -> bool:
    """Use status text, not a final numeric position (which DNF can retain)."""
    normalized = status.strip().lower()
    return (
        normalized == "finished"
        or normalized == "classified"
        or normalized == "lapped"
        or normalized.startswith("+")
    )


def _fraction(values: list[bool]) -> float | None:
    return fmean(float(value) for value in values) if values else None


def _improvement(
    values: list[int],
) -> float | None:
    """Positive means recent results are better; refuse tiny samples."""
    if len(values) < 5:
        return None
    recent = values[-3:]
    older = values[-8:-3]
    if len(older) < 2:
        return None
    return float(fmean(older) - fmean(recent))


def dynamics_feature_index(
    db: sqlite3.Connection,
) -> dict[DriverKey, tuple[float | None, ...]]:
    """Compute strictly-prior longitudinal features for completed races only.

    Rows are grouped by round *before* any participant from that round is
    added to driver or team history. Never use the target round's result,
    grid or status to form the target round's feature values.
    """
    source = db.execute(
        "SELECT r.season, r.round, r.driver_id, r.constructor_id, "
        "r.position, r.status, q.position "
        "FROM results r LEFT JOIN qualifying q "
        "ON r.season=q.season AND r.round=q.round "
        "AND r.driver_id=q.driver_id "
        "ORDER BY r.season, r.round, r.driver_id"
    ).fetchall()
    by_round: dict[tuple[int, int], list[tuple]] = defaultdict(list)
    for row in source:
        by_round[(row[0], row[1])].append(row)
    driver_history: dict[str, list[_PriorRace]] = defaultdict(list)
    constructor_history: dict[str, list[_PriorRace]] = defaultdict(list)
    output: dict[DriverKey, tuple[float | None, ...]] = {}

    for (season, round_number), entries in sorted(by_round.items()):
        # Calculate all participants from earlier rounds, atomically.
        for _, _, driver_id, constructor_id, _finish, _status, _qpos in entries:
            career = driver_history[driver_id]
            team = constructor_history[constructor_id]
            recent = career[-8:]
            current_year = [race for race in career if race.season == season]
            qualified = [
                race.qualified for race in career
                if race.qualified is not None
            ]
            finishes = [
                race.finish if race.classified and race.finish is not None else 25
                for race in career
            ]
            gains = [
                float(race.qualified - race.finish)
                for race in recent
                if race.classified
                and race.qualified is not None and race.finish is not None
            ]
            output[(season, round_number, driver_id)] = (
                float(len(career)),
                float(len(current_year)),
                _fraction([race.classified for race in recent]),
                _fraction([race.classified for race in team[-16:]]),
                _fraction([
                    bool(race.classified and race.finish is not None
                         and race.finish <= 4)
                    for race in recent
                ]),
                _improvement(finishes),
                _improvement(qualified),
                float(fmean(gains)) if gains else None,
            )
        # Only now may results from this round enter future history.
        for _, _, driver_id, constructor_id, finish, status, qualified in entries:
            prior = _PriorRace(
                season=season, constructor_id=constructor_id, finish=finish,
                qualified=qualified, classified=_classified(status),
            )
            driver_history[driver_id].append(prior)
            constructor_history[constructor_id].append(prior)
    return output


def with_dynamics(
    samples: list[TrainingSample],
    index: dict[DriverKey, tuple[float | None, ...]],
) -> list[TrainingSample]:
    """Append historical trends without changing target labels."""
    missing: tuple[float | None, ...] = (None,) * len(DYNAMICS_FEATURE_NAMES)
    return [
        replace(
            sample,
            values=sample.values + index.get(
                (sample.season, sample.round, sample.driver_id), missing
            ),
        )
        for sample in samples
    ]
