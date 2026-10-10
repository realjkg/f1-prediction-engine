"""Weather-aware historical completion rates with explicit timestamp fences.

OpenF1 weather is an *observation*, not a forecast. Historic observations may
label a completed prior race, but must NEVER be presented as if they were
issued before the target race. Current-race forecasts need a separate,
timestamped provider and an ingestion audit trail.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from f1engine.driver_dynamics import _classified

ALLOWED_OBSERVED_SOURCE = "openf1"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("weather timestamps must include a timezone")
    return value.astimezone(timezone.utc)


def _trusted_source(source: str) -> None:
    parsed = urlparse(source)
    if (parsed.scheme != "https" or not parsed.hostname
        or parsed.username or parsed.password or parsed.fragment):
        raise ValueError("weather source must be a verifiable HTTPS URL")


@dataclass(frozen=True)
class CompletedRaceWeather:
    season: int
    round: int
    ended_at: datetime
    observed_rain: bool
    source_url: str
    source_type: str = ALLOWED_OBSERVED_SOURCE

    def __post_init__(self) -> None:
        _utc(self.ended_at)
        _trusted_source(self.source_url)
        if self.source_type != ALLOWED_OBSERVED_SOURCE:
            raise ValueError("only verified historical observational sources allowed")
        if self.season < 1950 or self.round < 1:
            raise ValueError("invalid race identity")


@dataclass(frozen=True)
class PreRaceForecast:
    season: int
    round: int
    issued_at: datetime
    applies_at: datetime
    source_url: str
    rain_probability: float
    air_temperature_c: float | None = None
    track_temperature_c: float | None = None

    def __post_init__(self) -> None:
        issued, valid = _utc(self.issued_at), _utc(self.applies_at)
        _trusted_source(self.source_url)
        if valid <= issued:
            raise ValueError("forecast must precede the predicted conditions")
        if not 0.0 <= self.rain_probability <= 1.0:
            raise ValueError("rain probability must be in [0,1]")
        if self.season < 1950 or self.round < 1:
            raise ValueError("invalid race identity")

    def validate_as_of(self, cutoff: datetime) -> None:
        as_of = _utc(cutoff)
        if _utc(self.issued_at) > as_of:
            raise ValueError("weather forecast was published after the prediction cutoff")
        if as_of >= _utc(self.applies_at):
            raise ValueError("cannot use a forecast after its validity time")


@dataclass(frozen=True)
class WeatherReliability:
    wet_prior_races: int
    dry_prior_races: int
    wet_classification_rate: float | None
    dry_classification_rate: float | None
    forecast_weighted_classification_rate: float | None


def prior_weather_reliability(
    db: sqlite3.Connection,
    driver_id: str,
    historical: list[CompletedRaceWeather],
    forecast: PreRaceForecast,
    *,
    prediction_cutoff: datetime,
    minimum_per_condition: int = 2,
) -> WeatherReliability:
    """Use historical observed weather only for strictly earlier races.

    With incomplete condition samples, the forecast-weighted metric remains
    missing; replacing that uncertainty with a fabricated constant is not
    allowed in model search or production inference.
    """
    forecast.validate_as_of(prediction_cutoff)
    if minimum_per_condition < 1:
        raise ValueError("minimum_per_condition must be positive")
    conditions: dict[tuple[int, int], bool] = {}
    for observation in historical:
        key = (observation.season, observation.round)
        if key >= (forecast.season, forecast.round):
            raise ValueError("current or future observed race weather is leakage")
        if _utc(observation.ended_at) >= _utc(prediction_cutoff):
            raise ValueError("historical observation not completed by forecast cutoff")
        if key in conditions:
            raise ValueError("duplicate historical race-weather identity")
        conditions[key] = observation.observed_rain

    grouped: dict[bool, list[float]] = {True: [], False: []}
    for season, round_number, status in db.execute(
        "SELECT season, round, status FROM results WHERE driver_id=? "
        "AND (season < ? OR (season=? AND round < ?)) "
        "ORDER BY season, round",
        (driver_id, forecast.season, forecast.season, forecast.round),
    ):
        condition = conditions.get((season, round_number))
        if condition is not None:
            grouped[condition].append(float(_classified(status)))
    wet, dry = grouped[True], grouped[False]
    wet_mean = sum(wet) / len(wet) if len(wet) >= minimum_per_condition else None
    dry_mean = sum(dry) / len(dry) if len(dry) >= minimum_per_condition else None
    weighted = (
        forecast.rain_probability * wet_mean
        + (1.0 - forecast.rain_probability) * dry_mean
        if wet_mean is not None and dry_mean is not None else None
    )
    return WeatherReliability(
        wet_prior_races=len(wet), dry_prior_races=len(dry),
        wet_classification_rate=wet_mean,
        dry_classification_rate=dry_mean,
        forecast_weighted_classification_rate=weighted,
    )
