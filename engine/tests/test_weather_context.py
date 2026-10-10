"""Past observed conditions may inform durability; future conditions may not."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from f1engine.training_store import build_training_store
from f1engine.weather_context import (
    CompletedRaceWeather,
    PreRaceForecast,
    prior_weather_reliability,
)

UTC = timezone.utc


def forecast() -> PreRaceForecast:
    return PreRaceForecast(
        season=2021, round=3,
        issued_at=datetime(2021, 6, 28, tzinfo=UTC),
        applies_at=datetime(2021, 7, 1, tzinfo=UTC),
        source_url="https://weather.example.org/issued/2021-06-28",
        rain_probability=0.8,
    )


def observed(round_number: int, is_wet: bool) -> CompletedRaceWeather:
    return CompletedRaceWeather(
        season=2021, round=round_number,
        ended_at=datetime(2021, 6, round_number + 1, tzinfo=UTC),
        observed_rain=is_wet,
        source_url="https://api.openf1.org/v1/weather?session_key=1234",
    )


def test_weather_durability_requires_both_prior_condition_samples(
    mini_snapshot: Path, tmp_path: Path
) -> None:
    path = tmp_path / "f1.sqlite"
    build_training_store([mini_snapshot], path, as_of=date(2022, 1, 1))
    with sqlite3.connect(path) as db:
        stats = prior_weather_reliability(
            db, "test-driver",
            [observed(1, True), observed(2, False)],
            forecast(),
            prediction_cutoff=datetime(2021, 6, 29, tzinfo=UTC),
            minimum_per_condition=1,
        )
        assert stats.wet_prior_races == 1
        assert stats.dry_prior_races == 1
        assert stats.forecast_weighted_classification_rate is not None
        insufficient = prior_weather_reliability(
            db, "test-driver", [observed(1, True)], forecast(),
            prediction_cutoff=datetime(2021, 6, 29, tzinfo=UTC),
        )
        assert insufficient.forecast_weighted_classification_rate is None


def test_refuses_forecast_published_after_cutoff() -> None:
    with pytest.raises(ValueError, match="published after"):
        forecast().validate_as_of(datetime(2021, 6, 27, tzinfo=UTC))


def test_refuses_future_race_actual_weather(
    mini_snapshot: Path, tmp_path: Path
) -> None:
    path = tmp_path / "f1.sqlite"
    build_training_store([mini_snapshot], path, as_of=date(2022, 1, 1))
    with sqlite3.connect(path) as db:
        with pytest.raises(ValueError, match="leakage"):
            prior_weather_reliability(
                db, "test-driver", [observed(3, True)], forecast(),
                prediction_cutoff=datetime(2021, 6, 29, tzinfo=UTC),
            )


def test_rejects_untrustworthy_weather_claims() -> None:
    with pytest.raises(ValueError, match="timezone"):
        PreRaceForecast(
            season=2026, round=17,
            issued_at=datetime(2026, 10, 10),
            applies_at=datetime(2026, 10, 11, tzinfo=UTC),
            source_url="https://weather.example.org/forecast",
            rain_probability=0.4,
        )
    with pytest.raises(ValueError, match="HTTPS"):
        PreRaceForecast(
            season=2026, round=17,
            issued_at=datetime(2026, 10, 10, tzinfo=UTC),
            applies_at=datetime(2026, 10, 11, tzinfo=UTC),
            source_url="http://untrusted.local/",
            rain_probability=0.4,
        )
    with pytest.raises(ValueError, match="rain probability"):
        PreRaceForecast(
            season=2026, round=17,
            issued_at=datetime(2026, 10, 10, tzinfo=UTC),
            applies_at=datetime(2026, 10, 11, tzinfo=UTC),
            source_url="https://weather.example.org/forecast",
            rain_probability=98.0,
        )
