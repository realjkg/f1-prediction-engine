"""Research-only bridge: prior race-winner distribution + verified lap state.

A frozen, source-attributed pre-race model output is required. Never synthesize
it from the same race's classified result, current position, or 2024 demo
ledger. Blending coefficients are UNQUALIFIED until chosen on past race
replays, frozen and evaluated on unseen race checkpoints.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from f1engine.lap_trace import LapTraceRecord
from f1engine.race_simulator import InRaceScenario
from f1engine.wire import WireModel

FUSION_REVISION = "asof-prior-green-scenario-v1"


class PriorEvidenceError(ValueError):
    code = "PRIOR_EVIDENCE_INVALID"


class PreRacePrior(WireModel):
    """Exactly one race, frozen before its actual race start."""

    season: int = Field(ge=1950, le=2100)
    race_id: str = Field(min_length=1)
    session_key: int = Field(ge=1)
    model_revision: str = Field(min_length=1)
    model_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_issued_at: datetime
    frozen_at: datetime
    race_start_at: datetime
    driver_win_probabilities: dict[int, float] = Field(min_length=2, max_length=24)
    source_type: Literal["frozen-prerace-model"] = "frozen-prerace-model"
    # No optional "qualified" switch: nobody can toggle promotion through input.
    advisory_only: Literal[True] = True

    @field_validator("driver_win_probabilities")
    @classmethod
    def require_distribution(cls, values: dict[int, float]) -> dict[int, float]:
        if any(type(car) is not int or car <= 0 for car in values):
            raise ValueError("driver identities must be positive numbers")
        if any(not math.isfinite(p) or p < 0 or p > 1 for p in values.values()):
            raise ValueError("invalid winner prior")
        if not math.isclose(sum(values.values()), 1, abs_tol=1e-7):
            raise ValueError("winner prior must sum to one")
        return values

    @model_validator(mode="after")
    def require_prerace_cutoff(self) -> PreRacePrior:
        times = (self.source_issued_at, self.frozen_at, self.race_start_at)
        if any(t.tzinfo is None or t.utcoffset() is None for t in times):
            raise ValueError("prior times require timezone")
        source, frozen, start = (t.astimezone(UTC) for t in times)
        if not (source <= frozen < start):
            raise ValueError("frozen prior must precede race start")
        return self


class DriverUpdatedScenario(WireModel):
    driver_number: int
    pre_race_probability: float = Field(ge=0, le=1)
    green_continuation_frequency: float = Field(ge=0, le=1)
    blended_research_weight: float = Field(ge=0, le=1)
    current_position: int


class UpdatedScenario(WireModel):
    scenario_revision: Literal["asof-prior-green-scenario-v1"] = FUSION_REVISION
    status: Literal["unqualified-blend"] = "unqualified-blend"
    checkpoint_sha256: str
    source_prior_sha256: str
    model_revision: str
    lap: int
    total_laps: int
    prior_weight: float = Field(ge=0, le=1)
    green_scenario_weight: float = Field(ge=0, le=1)
    candidates: tuple[DriverUpdatedScenario, ...]
    explanation: str
    output_sha256: str
    promoted: Literal[False] = False
    advisory_only: Literal[True] = True


def combine_prerace_and_lap(
    prior: PreRacePrior, checkpoint: LapTraceRecord, scenario: InRaceScenario,
    *, green_scenario_weight: float,
) -> UpdatedScenario:
    """Experimental linear pool for paired benchmark against both inputs.

    The coefficient must be trained on an earlier chronologically separated
    racing cohort; it is an explicit, visible parameter, never learned from
    the race being predicted. No retrospective outcome enters this function.
    """
    if not math.isfinite(green_scenario_weight) or not 0 <= green_scenario_weight <= 1:
        raise PriorEvidenceError("candidate fusion weight must lie in [0,1]")
    observation = checkpoint.checkpoint
    if (
        (prior.season, prior.race_id, prior.session_key)
        != (observation.season, observation.race_id, observation.session_key)
    ):
        raise PriorEvidenceError("prior does not match the observed race/session")
    if observation.observed_at.astimezone(UTC) <= prior.frozen_at.astimezone(UTC):
        raise PriorEvidenceError("race observation must follow frozen pre-race prior")
    if scenario.checkpoint_record_sha256 != checkpoint.record_sha256:
        raise PriorEvidenceError("simulation and lap evidence hashes differ")
    if scenario.status != "experimental-scenario-only":
        raise PriorEvidenceError("incompatible scenario revision or status")
    cars = set(prior.driver_win_probabilities)
    if cars != {c.driver_number for c in scenario.drivers}:
        raise PriorEvidenceError("entrant/retirement mismatch; no silent renormalization")
    blended = []
    weights: dict[int, float] = {}
    for d in scenario.drivers:
        earlier = prior.driver_win_probabilities[d.driver_number]
        current = d.conditional_win_frequency
        weight = (1.0 - green_scenario_weight) * earlier + green_scenario_weight * current
        weights[d.driver_number] = weight
        blended.append(DriverUpdatedScenario(
            driver_number=d.driver_number,
            pre_race_probability=earlier,
            green_continuation_frequency=current,
            blended_research_weight=weight,
            current_position=d.current_position,
        ))
    if not math.isclose(sum(weights.values()), 1, abs_tol=1e-8):
        raise PriorEvidenceError("combined candidate distribution invalid")
    prior_bytes = json.dumps(prior.model_dump(mode="json", by_alias=True), sort_keys=True,
                             separators=(",", ":")).encode()
    prior_sha = hashlib.sha256(prior_bytes).hexdigest()
    result_hash = hashlib.sha256(json.dumps({
        "checkpoint": checkpoint.record_sha256,
        "scenario": scenario.scenario_sha256,
        "prior": prior_sha,
        "candidateRevision": FUSION_REVISION,
        "scenarioWeight": green_scenario_weight,
        "drivers": [b.model_dump(mode="json", by_alias=True) for b in blended],
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return UpdatedScenario(
        checkpoint_sha256=checkpoint.record_sha256,
        source_prior_sha256=prior_sha,
        model_revision=prior.model_revision,
        lap=observation.lap,
        total_laps=observation.total_laps,
        prior_weight=1-green_scenario_weight,
        green_scenario_weight=green_scenario_weight,
        candidates=tuple(blended),
        explanation=(
            "Research-only linear probability pool; no empirically validated "
            "coefficient, calibration, pit/reliability model, or deployment approval. "
            "Evaluate proper scores against pre-race and running-order baselines."
        ),
        output_sha256=result_hash,
    )
