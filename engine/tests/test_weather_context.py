"""Past observed conditions may inform durability; future conditions may not."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
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


def test_weather_is_driver_experience_modifier_not_race_determinant(
    mini_snapshot: Path, tmp_path: Path
) -> None:
    path = tmp_path / "f1.sqlite"
    build_training_store([mini_snapshot], path, as_of=date(2022, 1, 1))
    history = [observed(1, True), observed(2, False)]
    cutoff = datetime(2021, 6, 29, tzinfo=UTC)
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE results SET status='Mechanical' "
            "WHERE season=2021 AND round=2 AND driver_id='test-driver'"
        )
        wet_likely = prior_weather_reliability(
            db, "test-driver", history, forecast(),
            prediction_cutoff=cutoff, minimum_per_condition=1,
        )
        dry_likely = prior_weather_reliability(
            db, "test-driver", history,
            replace(forecast(), rain_probability=0.2),
            prediction_cutoff=cutoff, minimum_per_condition=1,
        )
    assert wet_likely.driver_baseline_classification_rate == pytest.approx(0.5)
    assert wet_likely.wet_classification_rate == pytest.approx(1.0)
    assert wet_likely.dry_classification_rate == pytest.approx(0.0)
    assert wet_likely.wet_experience_weight == pytest.approx(0.2)
    assert wet_likely.driver_condition_modifier == pytest.approx(0.06)
    assert wet_likely.forecast_weighted_classification_rate == pytest.approx(0.56)
    assert dry_likely.forecast_weighted_classification_rate == pytest.approx(0.44)
    assert wet_likely.forecast_weighted_classification_rate != pytest.approx(
        forecast().rain_probability
    )
