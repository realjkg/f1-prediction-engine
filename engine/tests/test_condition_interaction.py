"""Weather changes experienced demands; it never chooses a winner."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from f1engine.condition_interaction import (
    ConditionEvidenceError,
    ConditionForecast,
    DriverConditionProfile,
    conditional_winner_distribution,
)

H = "a" * 64
P = "b" * 64
START = datetime(2026, 10, 11, 13, 0, tzinfo=timezone.utc)
CUTOFF = START - timedelta(hours=2)
BASE = {"driver-a": 0.50, "driver-b": 0.30, "driver-c": 0.20}


def forecast(
    *, wet: float = 0.7, mixed: float = 0.2, dry: float = 0.1,
) -> ConditionForecast:
    return ConditionForecast(
        race_id="test-race", source_digest=H,
        issued_at=CUTOFF - timedelta(hours=3),
        prediction_cutoff=CUTOFF, race_start=START,
        dry_probability=dry, mixed_probability=mixed, wet_probability=wet,
    )


def profile(
    driver: str, *, wet_skill: float, races: int = 16,
    mixed_skill: float = 0.0,
) -> DriverConditionProfile:
    return DriverConditionProfile(
        driver_id=driver, source_digest=P,
        history_through=CUTOFF - timedelta(days=7),
        mixed_starts=races, wet_starts=races,
        mixed_skill_delta=mixed_skill, wet_skill_delta=wet_skill,
    )


def test_condition_adjustment_neutral_by_default() -> None:
    adjustment = conditional_winner_distribution(
        BASE, forecast(), {"driver-a": profile("driver-a", wet_skill=1.0)}
    )
    assert adjustment.winner == pytest.approx(BASE)
    assert all(shift == 0 for shift in adjustment.logit_shifts.values())
    assert adjustment.weather_source_digest == H


def test_weather_does_not_determine_winner() -> None:
    # Changes relative ability only when a separately qualified strength is
    # supplied; dry weather has exactly zero effect regardless of reputation.
    strong = {"driver-b": profile("driver-b", wet_skill=1.0, races=80)}
    wet = conditional_winner_distribution(
        BASE, forecast(wet=1.0, mixed=0, dry=0),
        strong, candidate_strength=0.2,
    )
    assert wet.winner["driver-b"] > BASE["driver-b"]
    # Wet experience changes the probability without forcing a winner.
    assert wet.winner["driver-a"] > wet.winner["driver-b"]
    assert sum(wet.winner.values()) == pytest.approx(1.0)
    dry = conditional_winner_distribution(
        BASE, forecast(wet=0, mixed=0, dry=1),
        strong, candidate_strength=1.0,
    )
    assert dry.winner == pytest.approx(BASE)


def test_small_wet_history_is_shrunk_to_neutral() -> None:
    single = conditional_winner_distribution(
        BASE, forecast(wet=1.0, mixed=0, dry=0),
        {"driver-b": profile("driver-b", wet_skill=1.0, races=1)},
        candidate_strength=1,
    )
    many = conditional_winner_distribution(
        BASE, forecast(wet=1.0, mixed=0, dry=0),
        {"driver-b": profile("driver-b", wet_skill=1.0, races=80)},
        candidate_strength=1,
    )
    assert 0 < single.logit_shifts["driver-b"] < many.logit_shifts["driver-b"] < 1
    assert BASE["driver-b"] < single.winner["driver-b"] < many.winner["driver-b"]


def test_driver_names_never_generate_special_treatment() -> None:
    # No hard-coded classifications or favored driver names.
    without = conditional_winner_distribution(
        {"max_verstappen": 0.5, "lando_norris": 0.5},
        forecast(),
        {},
        candidate_strength=1,
    )
    assert without.winner == {"max_verstappen": 0.5, "lando_norris": 0.5}


def test_mixed_conditions_change_only_matching_experience() -> None:
    inputs = {"driver-c": profile(
        "driver-c", wet_skill=-0.6, mixed_skill=0.8, races=20,
    )}
    mixed = conditional_winner_distribution(
        BASE, forecast(wet=0, mixed=1, dry=0),
        inputs, candidate_strength=1,
    )
    wet = conditional_winner_distribution(
        BASE, forecast(wet=1, mixed=0, dry=0),
        inputs, candidate_strength=1,
    )
    assert mixed.logit_shifts["driver-c"] > 0
    assert wet.logit_shifts["driver-c"] < 0
    assert mixed.winner["driver-c"] > BASE["driver-c"] > wet.winner["driver-c"]


def test_forecast_must_precede_prediction_and_race() -> None:
    with pytest.raises(ConditionEvidenceError, match="pre-race cutoff"):
        conditional_winner_distribution(
            BASE, replace(forecast(), issued_at=CUTOFF + timedelta(seconds=1)), {}
        )
    with pytest.raises(ConditionEvidenceError, match="pre-race cutoff"):
        conditional_winner_distribution(
            BASE, replace(forecast(), prediction_cutoff=START), {}
        )
    with pytest.raises(ConditionEvidenceError, match="timezone"):
        conditional_winner_distribution(
            BASE, replace(forecast(), issued_at=CUTOFF.replace(tzinfo=None)), {}
        )


def test_unverified_driver_history_is_rejected() -> None:
    future = replace(
        profile("driver-a", wet_skill=0.5),
        history_through=START + timedelta(days=1),
    )
    with pytest.raises(ConditionEvidenceError, match="future evidence"):
        conditional_winner_distribution(BASE, forecast(), {"driver-a": future})
    with pytest.raises(ConditionEvidenceError, match="identity"):
        conditional_winner_distribution(
            BASE, forecast(), {"driver-a": profile("driver-b", wet_skill=0.5)}
        )


@pytest.mark.parametrize("values", [
    (0.8, 0.8, 0.0), (float("nan"), 0.1, 0.1), (-0.1, 0.1, 1.0),
])
def test_invalid_weather_regime_probabilities_fail_closed(values) -> None:
    with pytest.raises(ConditionEvidenceError, match="weather"):
        conditional_winner_distribution(
            BASE, forecast(wet=values[0], mixed=values[1], dry=values[2]), {}
        )


def test_missing_profiles_are_neutral_but_invalid_entrants_refused() -> None:
    neutral = conditional_winner_distribution(BASE, forecast(), {}, candidate_strength=1)
    assert neutral.winner == pytest.approx(BASE)
    with pytest.raises(ConditionEvidenceError, match="starter field"):
        conditional_winner_distribution(
            BASE, forecast(),
            {"not-entered": profile("not-entered", wet_skill=1.0)},
        )


def test_rejected_extreme_strength_and_unbounded_skill() -> None:
    with pytest.raises(ConditionEvidenceError, match="strength"):
        conditional_winner_distribution(BASE, forecast(), {}, candidate_strength=1.1)
    with pytest.raises(ConditionEvidenceError, match="unbounded"):
        conditional_winner_distribution(
            BASE, forecast(), {
                "driver-a": profile("driver-a", wet_skill=5.0)
            }, candidate_strength=1,
        )
