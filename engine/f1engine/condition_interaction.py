"""Optional, auditable weather-by-driver *interaction* for F1 predictions.

Race conditions modify the effect of demonstrated driver and vehicle ability;
they never determine a race outcome. This experimental adapter is disabled
without timestamped pre-race source evidence and separately validated skill
estimates. Nothing calls it in the serving path until a challenger qualifies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping


class ConditionEvidenceError(ValueError):
    """Missing or inconsistent evidence for conditional inference."""


@dataclass(frozen=True)
class ConditionForecast:
    """A source-attributed forecast frozen before the GP start.

    The three probabilities are weather-regime probabilities at the race,
    NOT a hindsight classification based on conditions that actually occurred.
    """

    race_id: str
    source_digest: str
    issued_at: datetime
    prediction_cutoff: datetime
    race_start: datetime
    dry_probability: float
    mixed_probability: float
    wet_probability: float


@dataclass(frozen=True)
class DriverConditionProfile:
    """Constructor-adjusted driver condition effects learned from past races.

    Performance deltas are bounded dimensionless *skill residuals*, not win
    probabilities. The evaluator must derive them from only earlier races,
    accounting for constructor strength, qualifying and field difficulty.
    """

    driver_id: str
    source_digest: str
    history_through: datetime
    mixed_starts: int
    wet_starts: int
    mixed_skill_delta: float
    wet_skill_delta: float


@dataclass(frozen=True)
class ConditionAdjustedPrediction:
    """Detached challenger prediction with evidence, never silent production."""

    winner: dict[str, float]
    base_winner: dict[str, float]
    logit_shifts: dict[str, float]
    weather_source_digest: str
    forecast_issued_at: str
    prediction_cutoff: str
    candidate_strength: float


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ConditionEvidenceError(f"{name} must carry a timezone")
    return value.astimezone(timezone.utc)


def _valid_digest(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _validate_forecast(forecast: ConditionForecast) -> None:
    if not forecast.race_id or not _valid_digest(forecast.source_digest):
        raise ConditionEvidenceError("identified, SHA-256-bound weather source required")
    issued = _aware_utc(forecast.issued_at, "issued_at")
    cutoff = _aware_utc(forecast.prediction_cutoff, "prediction_cutoff")
    start = _aware_utc(forecast.race_start, "race_start")
    if not issued <= cutoff < start:
        raise ConditionEvidenceError("forecast must be issued by the pre-race cutoff")
    values = (
        forecast.dry_probability, forecast.mixed_probability,
        forecast.wet_probability,
    )
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in values):
        raise ConditionEvidenceError("invalid weather regime probabilities")
    if not math.isclose(sum(values), 1.0, abs_tol=1e-9):
        raise ConditionEvidenceError("weather regimes must sum to one")


def _validate_profile(profile: DriverConditionProfile, cutoff: datetime) -> None:
    if not profile.driver_id or not _valid_digest(profile.source_digest):
        raise ConditionEvidenceError("unidentified or unsourced driver profile")
    if _aware_utc(profile.history_through, "history_through") > cutoff:
        raise ConditionEvidenceError("driver skill profile contains future evidence")
    if profile.mixed_starts < 0 or profile.wet_starts < 0:
        raise ConditionEvidenceError("negative historical sample count")
    if any(
        not math.isfinite(v) or not -1 <= v <= 1
        for v in (profile.mixed_skill_delta, profile.wet_skill_delta)
    ):
        raise ConditionEvidenceError("unbounded driver condition skill delta")


def conditional_winner_distribution(
    baseline: Mapping[str, float],
    forecast: ConditionForecast,
    profiles: Mapping[str, DriverConditionProfile],
    *,
    candidate_strength: float = 0.0,
    shrinkage_races: float = 8.0,
) -> ConditionAdjustedPrediction:
    """Apply weather × *historically trained* driver skill in log-probability.

    Zero strength means unchanged baseline. The candidate strength is chosen
    solely by chronological model evaluation; it is never increased to
    reproduce a known outcome. Missing driver histories produce neutral
    effects. Max possible logit shift is candidate_strength; no driver is
    automatically boosted or penalized based on a name or reputation.
    """
    _validate_forecast(forecast)
    if not math.isfinite(candidate_strength) or not 0 <= candidate_strength <= 1:
        raise ConditionEvidenceError("candidate strength must be in [0,1]")
    if not math.isfinite(shrinkage_races) or shrinkage_races <= 0:
        raise ConditionEvidenceError("shrinkage sample count must be positive")
    if not baseline or set(profiles) - set(baseline):
        raise ConditionEvidenceError("condition profiles do not match the starter field")
    if any(not isinstance(k, str) or not k for k in baseline):
        raise ConditionEvidenceError("blank driver identity")
    if any(not math.isfinite(p) or p < 0 for p in baseline.values()):
        raise ConditionEvidenceError("invalid baseline win probability")
    total_base = sum(baseline.values())
    if not math.isclose(total_base, 1.0, abs_tol=1e-8):
        raise ConditionEvidenceError("base winner probabilities must sum to one")
    cutoff = _aware_utc(forecast.prediction_cutoff, "prediction_cutoff")
    for driver_id, profile in profiles.items():
        if driver_id != profile.driver_id:
            raise ConditionEvidenceError("profile identity does not match driver key")
        _validate_profile(profile, cutoff)

    def shrink(sample: int) -> float:
        return sample / (sample + shrinkage_races)

    shifts: dict[str, float] = {}
    raw: dict[str, float] = {}
    for driver_id, base in baseline.items():
        profile = profiles.get(driver_id)
        evidence_effect = 0.0
        if profile is not None:
            evidence_effect = (
                forecast.mixed_probability
                * shrink(profile.mixed_starts)
                * profile.mixed_skill_delta
                + forecast.wet_probability
                * shrink(profile.wet_starts)
                * profile.wet_skill_delta
            )
        shift = candidate_strength * evidence_effect
        shifts[driver_id] = shift
        raw[driver_id] = base * math.exp(shift)
    total = sum(raw.values())
    if total <= 0:
        raise ConditionEvidenceError("degenerate conditional distribution")
    return ConditionAdjustedPrediction(
        winner={driver_id: raw[driver_id] / total for driver_id in baseline},
        base_winner=dict(baseline),
        logit_shifts=shifts,
        weather_source_digest=forecast.source_digest,
        forecast_issued_at=forecast.issued_at.isoformat(),
        prediction_cutoff=forecast.prediction_cutoff.isoformat(),
        candidate_strength=candidate_strength,
    )
