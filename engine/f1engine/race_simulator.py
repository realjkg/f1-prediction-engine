"""Bounded experimental in-race conditional simulation.

No training data, pit prediction, or realized finish order is used here.
This is a *scenario*, not a calibrated forecast or live model promotion:
its frequencies describe a no-additional-stops, green-flag continuation
under pace estimated only from the checkpoint's completed laps.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from statistics import median, pstdev
from typing import Literal

from pydantic import Field, model_validator

from f1engine.lap_trace import LapTraceRecord
from f1engine.wire import WireModel

SCENARIO_REVISION = "green-pace-no-stops-v1"
MAX_TRIALS = 10000
MIN_TRIALS = 200


class ScenarioUnavailable(ValueError):
    """Source coverage, racing state, or pace evidence is insufficient."""

    code = "SCENARIO_UNAVAILABLE"


class DriverScenario(WireModel):
    driver_number: int
    current_position: int
    current_gap_seconds: float
    conditional_win_frequency: float = Field(ge=0, le=1)
    conditional_top_four_frequency: float = Field(ge=0, le=1)
    estimated_green_lap_seconds: float = Field(gt=0)


class InRaceScenario(WireModel):
    schema_version: Literal[1] = 1
    scenario_revision: Literal["green-pace-no-stops-v1"] = SCENARIO_REVISION
    status: Literal["experimental-scenario-only"] = "experimental-scenario-only"
    season: int
    race_id: str
    session_key: int
    checkpoint_lap: int
    total_laps: int
    remaining_laps: int
    checkpoint_record_sha256: str
    observed_at: str
    seed: int
    trials: int
    assumptions: tuple[str, ...]
    drivers: tuple[DriverScenario, ...]
    scenario_sha256: str
    advisory_only: Literal[True] = True

    @model_validator(mode="after")
    def correct_frequencies(self) -> InRaceScenario:
        if not math.isclose(
            sum(d.conditional_win_frequency for d in self.drivers), 1.0,
            abs_tol=1e-7,
        ):
            raise ValueError("conditional win frequencies must sum to 1")
        return self


def simulate_green_pace(
    record: LapTraceRecord, *, trials: int = 2000, seed: int | None = None,
) -> InRaceScenario:
    """Simulate finishes from verified observed order, gaps, and recent pace.

    For each entrant, compute the median of their last three fully observed
    racing laps and a finite bounded per-lap jitter. The toy scenario assumes
    no future pits, incidents, retirements, lapping effects or cautions. It
    intentionally refuses incomplete numeric gaps and safety-car conditions.
    Validate out-of-sample before building a statistically qualified model.
    """
    c = record.checkpoint
    if c.track_status != "GREEN" or c.lap >= c.total_laps:
        raise ScenarioUnavailable("green-flag race with remaining laps required")
    if not MIN_TRIALS <= trials <= MAX_TRIALS:
        raise ScenarioUnavailable("trials outside bounded simulation range")
    if c.source_type == "synthetic-fixture":
        # Fixture scenarios can exercise code paths, never support a live claim.
        pass
    entries = list(c.running_order)
    if len(entries) < 2 or len(entries) > 24:
        raise ScenarioUnavailable("unsupported number of verified drivers")
    if [e.position for e in entries] != list(range(1, len(entries) + 1)):
        raise ScenarioUnavailable("running order is incomplete or non-contiguous")
    state: list[tuple[int, int, float, float, float]] = []
    for entrant in entries:
        gap = entrant.gap_to_leader_seconds
        # The leader's missing gap is unambiguously zero, not a missing measurement.
        if entrant.position == 1 and gap is None:
            gap = 0.0
        if gap is None or not math.isfinite(gap):
            raise ScenarioUnavailable("numeric gaps to leader are required for every driver")
        if gap > 300:
            raise ScenarioUnavailable("lapped or unbounded car gap cannot be projected")
        sample = entrant.recent_lap_seconds
        if len(sample) < 3:
            raise ScenarioUnavailable("three confirmed recent green laps required per driver")
        recent = sample[-3:]
        pace = float(median(recent))
        if pace < 50 or pace > 220 or any(abs(t - pace) > pace * .08 for t in recent):
            raise ScenarioUnavailable("abnormal recent lap times; cannot infer green pace")
        scatter = max(.18, min(2.0, pstdev(recent)))
        state.append((entrant.driver_number, entrant.position, gap, pace, scatter))

    horizon = c.total_laps - c.lap
    scenario_seed = (
        int(hashlib.sha256(
            (record.record_sha256 + SCENARIO_REVISION).encode()
        ).hexdigest()[:16], 16)
        if seed is None else seed
    )
    if not 0 <= scenario_seed < 2**64:
        raise ScenarioUnavailable("seed must be an unsigned 64-bit integer")
    rng = random.Random(scenario_seed)
    win = {entry[0]: 0 for entry in state}
    four = {entry[0]: 0 for entry in state}
    root_horizon = math.sqrt(horizon)
    for _ in range(trials):
        projected = [
            (gap + horizon * pace + rng.gauss(0.0, root_horizon * jitter), position, car)
            for car, position, gap, pace, jitter in state
        ]
        projected.sort()
        win[projected[0][2]] += 1
        for _, _, car in projected[:4]:
            four[car] += 1
    results = tuple(
        DriverScenario(
            driver_number=car,
            current_position=position,
            current_gap_seconds=gap,
            conditional_win_frequency=win[car] / trials,
            conditional_top_four_frequency=four[car] / trials,
            estimated_green_lap_seconds=pace,
        )
        for car, position, gap, pace, _ in state
    )
    assumptions = (
        "Conditional simulation only: NOT calibrated real-world win probabilities.",
        "All remaining laps assumed green with no further stops, incidents, or retirements.",
        "Pace from only each driver's last three validated completed green-flag laps.",
        "Independent limited pace noise; traffic, tire wear, regulation and strategy omitted.",
        "Source/field coverage and historical model validation must precede promotion.",
    )
    canonical = {
        "revision": SCENARIO_REVISION,
        "checkpointSha256": record.record_sha256,
        "seed": scenario_seed,
        "trials": trials,
        "assumptions": assumptions,
        "drivers": [e.model_dump(mode="json", by_alias=True) for e in results],
    }
    scenario_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return InRaceScenario(
        season=c.season, race_id=c.race_id, session_key=c.session_key,
        checkpoint_lap=c.lap, total_laps=c.total_laps, remaining_laps=horizon,
        checkpoint_record_sha256=record.record_sha256,
        observed_at=c.observed_at.isoformat(), seed=scenario_seed,
        trials=trials, assumptions=assumptions, drivers=results,
        scenario_sha256=scenario_hash,
    )
