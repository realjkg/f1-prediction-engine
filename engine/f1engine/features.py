"""As-of feature builder — strict no-lookahead.

Contract (spec, engine/f1engine/features): rolling driver form, qualifying
deltas (vs teammate, vs pole), team strength, and track history — where
features for round N use ONLY rounds < N. The load-bearing guarantee of the
whole predictor: nothing computed here can see a round's own results, its
qualifying, or anything later. Two tests enforce this from both directions
(test_features.py): future rounds removed, and the round's own rows tampered,
must both leave round-N features byte-identical.

Row universe: one feature row per (season, round, driver) present in that
round's results. The results table is the snapshot's only record of who
entered a race; entry lists are known before a race in reality, so keying
rows by it is not leakage — but every feature VALUE below is computed
strictly from strictly-prior rounds.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field

from f1engine.ingestion import (
    PinnedDataset,
    QualifyingRow,
    RaceRow,
    ResultRow,
)

# Finish placeholder for non-classified results (DNF/WD/NP): worse than any
# classified finisher in a 20-car field.
UNCLASSIFIED_FINISH = 25.0

RoundKey = tuple[int, int]  # (season, round)


class AsOfFeatureRow(BaseModel):
    """One driver's predictive features for one round — prior data only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    season: int = Field(ge=1950, le=2100)
    round: int = Field(ge=1, le=100)
    race_id: str = Field(min_length=1)
    driver_id: str = Field(min_length=1)
    constructor_id: str = Field(min_length=1)

    starts: int = Field(ge=0)  # prior rounds with a result for this driver
    form_finish_mean: float | None = None  # mean finish over the window
    form_finish_mean_all: float | None = None  # mean finish over all priors
    q_best_ms: int | None = None  # best qualifying time in the window
    q_delta_teammate_ms: float | None = None  # mean gap to fastest teammate
    q_delta_pole_ms: float | None = None  # mean gap to that round's pole
    team_points_mean: float | None = None  # constructor points per round
    track_finish_mean: float | None = None  # at this race_id, prior seasons


class FeatureTable(BaseModel):
    """The full as-of feature table over a pinned dataset."""

    model_config = ConfigDict(frozen=True)

    form_window: int = Field(ge=1)
    rows: tuple[AsOfFeatureRow, ...]


def numeric_finish(row: ResultRow) -> float:
    """Position as a float; non-classified results get the penalty value."""
    return float(row.position) if row.position is not None else UNCLASSIFIED_FINISH


def best_qualifying_ms(row: QualifyingRow) -> int | None:
    """Fastest session time of a qualifying entry, in ms (None if absent)."""
    times = [t for t in (row.q1_ms, row.q2_ms, row.q3_ms) if t is not None]
    return min(times) if times else None


@dataclass(frozen=True)
class _RoundIndex:
    """Per-round facts, precomputed once so per-driver rows are O(1) lookups."""

    drivers_in_order: tuple[str, ...]  # finish order, deduplicated
    driver_constructor: dict[str, str]  # driver → constructor that round
    driver_finishes: dict[str, list[float]]  # driver → numeric finishes
    pole_ms: int | None  # fastest qualifying time of the round
    constructor_q: dict[
        str, tuple[tuple[str, int], ...]
    ]  # constructor → (driver, best q)
    team_points: dict[str, float]  # constructor → points scored this round


@dataclass(frozen=True)
class _DatasetIndex:
    rounds: list[RoundKey]
    races_by_round: dict[RoundKey, RaceRow]
    by_round: dict[RoundKey, _RoundIndex]
    driver_rounds: dict[str, set[RoundKey]]  # driver → rounds with a result
    driver_track_finishes: dict[
        tuple[str, str], list[tuple[RoundKey, float]]
    ]  # (driver, race_id) → [(round, mean finish)]


def _index_dataset(dataset: PinnedDataset) -> _DatasetIndex:
    races_by_round: dict[RoundKey, RaceRow] = {
        (race.season, race.round): race for race in dataset.races
    }
    rounds = sorted(races_by_round)

    results_by_round: dict[RoundKey, list[ResultRow]] = {}
    for row in dataset.results:
        results_by_round.setdefault((row.season, row.round), []).append(row)

    qualifying_by_round: dict[RoundKey, list[QualifyingRow]] = {}
    for row in dataset.qualifying:
        qualifying_by_round.setdefault((row.season, row.round), []).append(row)

    by_round: dict[RoundKey, _RoundIndex] = {}
    for key in rounds:
        results = sorted(
            results_by_round.get(key, []),
            key=lambda row: (numeric_finish(row), row.driver_id),
        )
        driver_finishes: dict[str, list[float]] = {}
        driver_constructor: dict[str, str] = {}
        drivers_in_order: list[str] = []
        team_points: dict[str, float] = {}
        for row in results:
            driver_finishes.setdefault(row.driver_id, []).append(
                numeric_finish(row)
            )
            driver_constructor.setdefault(row.driver_id, row.constructor_id)
            if row.driver_id not in drivers_in_order:
                drivers_in_order.append(row.driver_id)
            team_points[row.constructor_id] = (
                team_points.get(row.constructor_id, 0.0) + float(row.points)
            )

        best_q: dict[str, int] = {}
        constructor_of: dict[str, str] = {}
        for row in qualifying_by_round.get(key, []):
            time = best_qualifying_ms(row)
            if time is None:
                continue
            constructor_of.setdefault(row.driver_id, row.constructor_id)
            current = best_q.get(row.driver_id)
            if current is None or time < current:
                best_q[row.driver_id] = time
        pole_ms = min(best_q.values()) if best_q else None
        constructor_q: dict[str, list[tuple[str, int]]] = {}
        for driver_id, time in best_q.items():
            constructor_q.setdefault(constructor_of[driver_id], []).append(
                (driver_id, time)
            )

        by_round[key] = _RoundIndex(
            drivers_in_order=tuple(drivers_in_order),
            driver_constructor=driver_constructor,
            driver_finishes=driver_finishes,
            pole_ms=pole_ms,
            constructor_q={
                name: tuple(entries) for name, entries in constructor_q.items()
            },
            team_points=team_points,
        )

    driver_rounds: dict[str, set[RoundKey]] = {}
    driver_track_finishes: dict[
        tuple[str, str], list[tuple[RoundKey, float]]
    ] = {}
    for key, round_index in by_round.items():
        race = races_by_round[key]
        for driver_id, finishes in round_index.driver_finishes.items():
            driver_rounds.setdefault(driver_id, set()).add(key)
            driver_track_finishes.setdefault((driver_id, race.race_id), []).append(
                (key, fmean(finishes))
            )

    return _DatasetIndex(
        rounds=rounds,
        races_by_round=races_by_round,
        by_round=by_round,
        driver_rounds=driver_rounds,
        driver_track_finishes=driver_track_finishes,
    )


def _driver_features_for_round(
    season: int,
    round_number: int,
    race: RaceRow,
    driver_id: str,
    constructor_id: str,
    prior_rounds: list[RoundKey],
    window_rounds: set[RoundKey],
    index: _DatasetIndex,
) -> AsOfFeatureRow:
    all_time_finishes: list[float] = []
    window_finishes: list[float] = []
    window_q_best: list[int] = []
    teammate_gaps: list[float] = []
    pole_gaps: list[float] = []
    team_points: list[float] = []

    for key in prior_rounds:
        round_index = index.by_round[key]
        finishes = round_index.driver_finishes.get(driver_id)
        if finishes is not None:
            all_time_finishes.extend(finishes)
            if key in window_rounds:
                window_finishes.extend(finishes)

        if key not in window_rounds:
            continue

        if constructor_id in round_index.team_points:
            team_points.append(round_index.team_points[constructor_id])

        entries = round_index.constructor_q.get(constructor_id, ())
        driver_q = next(
            (time for driver, time in entries if driver == driver_id), None
        )
        if driver_q is not None:
            window_q_best.append(driver_q)
            if round_index.pole_ms is not None:
                pole_gaps.append(float(driver_q - round_index.pole_ms))
            teammate_best = min(
                (time for driver, time in entries if driver != driver_id),
                default=None,
            )
            if teammate_best is not None:
                teammate_gaps.append(float(driver_q - teammate_best))

    track_finishes = [
        finish
        for key, finish in index.driver_track_finishes.get(
            (driver_id, race.race_id), []
        )
        if key[0] < season  # prior seasons only — same race, earlier years
    ]

    return AsOfFeatureRow(
        season=season,
        round=round_number,
        race_id=race.race_id,
        driver_id=driver_id,
        constructor_id=constructor_id,
        starts=len(index.driver_rounds.get(driver_id, set()) & set(prior_rounds)),
        form_finish_mean=fmean(window_finishes) if window_finishes else None,
        form_finish_mean_all=fmean(all_time_finishes) if all_time_finishes else None,
        q_best_ms=min(window_q_best) if window_q_best else None,
        q_delta_teammate_ms=fmean(teammate_gaps) if teammate_gaps else None,
        q_delta_pole_ms=fmean(pole_gaps) if pole_gaps else None,
        team_points_mean=fmean(team_points) if team_points else None,
        track_finish_mean=fmean(track_finishes) if track_finishes else None,
    )


def build_asof_features(
    dataset: PinnedDataset,
    *,
    form_window: int = 5,
    through_round: int | None = None,
) -> FeatureTable:
    """Build the as-of feature table over the pinned dataset.

    Every row's values are computed strictly from rounds BEFORE the row's own
    round (lexicographic (season, round) order), never from the round itself
    or anything later. ``through_round``, when set, only bounds which target
    rounds are emitted (round < through_round in every season) — it never
    changes any row's values.
    """
    if form_window < 1:
        raise ValueError(f"form_window must be >= 1, got {form_window}")

    index = _index_dataset(dataset)

    rows: list[AsOfFeatureRow] = []
    for position, (season, round_number) in enumerate(index.rounds):
        if through_round is not None and round_number >= through_round:
            continue
        prior_rounds = index.rounds[:position]
        window_rounds = set(prior_rounds[-form_window:])
        race = index.races_by_round[(season, round_number)]
        round_index = index.by_round[(season, round_number)]

        for driver_id in round_index.drivers_in_order:
            rows.append(
                _driver_features_for_round(
                    season=season,
                    round_number=round_number,
                    race=race,
                    driver_id=driver_id,
                    constructor_id=round_index.driver_constructor[driver_id],
                    prior_rounds=prior_rounds,
                    window_rounds=window_rounds,
                    index=index,
                )
            )

    return FeatureTable(form_window=form_window, rows=tuple(rows))
