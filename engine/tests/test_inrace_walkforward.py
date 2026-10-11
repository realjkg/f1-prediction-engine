"""Forward-only winner accuracy qualification tests (synthetic events only)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from datetime import UTC, datetime, timedelta

import pytest

from f1engine.inrace_evaluation import FrozenEvaluationCase
from f1engine.inrace_walkforward import (
    evaluate_forward_weights,
    read_forward_report,
    write_forward_report,
)
from f1engine.lap_trace import DriverOnTrack, LapCheckpoint, LapTraceRecord
from f1engine.live_prior import PreRacePrior, combine_prerace_and_lap
from f1engine.race_simulator import simulate_green_pace

FIRST = datetime(2026, 2, 1, 16, tzinfo=UTC)


def frozen_case(
    index: int, *,
    winner: int = 16, result_delay_hours: int = 2,
    prior_distribution: dict[int, float] | None = None,
) -> FrozenEvaluationCase:
    observed_at = FIRST + timedelta(days=7 * index)
    race_id = f"fictional-gp-{index}"
    rows = (
        DriverOnTrack(
            driver_number=1, position=1, gap_to_leader_seconds=0,
            recent_lap_seconds=(101.0, 100.9, 101.1),
        ),
        DriverOnTrack(
            driver_number=16, position=2, gap_to_leader_seconds=3.0,
            recent_lap_seconds=(100.4, 100.5, 100.3),
        ),
        DriverOnTrack(
            driver_number=44, position=3, gap_to_leader_seconds=16.0,
            recent_lap_seconds=(101.2, 101.3, 101.1),
        ),
    )
    checkpoint = LapCheckpoint(
        season=2026, race_id=race_id, session_key=90000 + index,
        lap=25, total_laps=62, observed_at=observed_at,
        captured_at=observed_at + timedelta(seconds=3),
        provider="test-synthetic", source_type="synthetic-fixture",
        source_payload_sha256=f"{index+1:064x}",
        track_status="GREEN", running_order=rows,
    )
    record = LapTraceRecord(
        checkpoint=checkpoint, record_sha256=f"{index+101:064x}"
    )
    scenario = simulate_green_pace(record, trials=300, seed=100 + index)
    prior = PreRacePrior(
        season=2026, race_id=race_id, session_key=90000 + index,
        model_revision="frozen-experimental-prior-v1",
        model_artifact_sha256="b" * 64,
        dataset_sha256="c" * 64,
        source_issued_at=observed_at - timedelta(hours=3),
        frozen_at=observed_at - timedelta(hours=2),
        race_start_at=observed_at - timedelta(hours=1),
        driver_win_probabilities=prior_distribution or {1: .65, 16: .25, 44: .10},
    )
    blend = combine_prerace_and_lap(
        prior, record, scenario, green_scenario_weight=.5,
    )
    return FrozenEvaluationCase(
        season=2026, race_id=race_id, lap=25,
        observed_at=observed_at,
        result_published_at=observed_at + timedelta(hours=result_delay_hours),
        winner_driver_number=winner,
        initial_prior=prior.driver_win_probabilities,
        scenario=scenario, combined=blend,
    )


def test_forward_weight_selection_uses_only_completed_earlier_events() -> None:
    cases = [frozen_case(i) for i in range(7)]
    report = evaluate_forward_weights(cases)
    assert report.model_promotion_allowed is False
    assert report.research_only is True
    assert report.scored_races == 3
    assert report.unscored_races == 4
    assert [f.training_races for f in report.folds] == [4, 5, 6]
    assert report.folds[0].selected_scenario_weight > 0.5
    assert set(report.paired_summary) == {
        "pre-race", "running-order", "green-continuation", "walkforward-fusion",
    }
    assert len(report.report_sha256) == 64
    assert report == evaluate_forward_weights(list(reversed(cases)))
    for fold in report.folds:
        assert fold.last_training_result_at < fold.as_of
        assert 0 <= fold.selected_scenario_weight <= 1
        assert fold.training_races >= 4


def test_later_winner_label_cannot_retrain_same_event_or_earlier_fold() -> None:
    cases = [frozen_case(i) for i in range(7)]
    original = evaluate_forward_weights(cases)
    changed = list(cases)
    changed[-1] = replace(changed[-1], winner_driver_number=1)
    updated = evaluate_forward_weights(changed)
    assert original.folds[-1].selected_scenario_weight == (
        updated.folds[-1].selected_scenario_weight
    )
    assert original.folds[:-1] == updated.folds[:-1]
    assert original.folds[-1].winner_log_loss != updated.folds[-1].winner_log_loss


def test_results_not_published_before_target_are_excluded() -> None:
    cases = [frozen_case(i) for i in range(7)]
    cases[3] = replace(
        cases[3],
        result_published_at=cases[5].observed_at + timedelta(seconds=2),
    )
    report = evaluate_forward_weights(cases)
    # Lap 25 at race 4 is not a known training label for race 5 or race 6.
    assert report.scored_races == 2
    assert report.folds[0].race_id == "fictional-gp-5"
    assert report.folds[0].training_races == 4


def test_multiple_laps_same_race_are_not_independent_samples() -> None:
    cases = [frozen_case(i) for i in range(6)]
    second_lap = replace(cases[2], lap=26)
    with pytest.raises(ValueError, match="one prespecified checkpoint"):
        evaluate_forward_weights(cases + [second_lap])


def test_tampered_prior_or_future_freeze_is_rejected() -> None:
    cases = [frozen_case(i) for i in range(6)]
    target = cases[-1]
    cases[-1] = replace(target, initial_prior={1: .25, 16: .65, 44: .10})
    with pytest.raises(ValueError, match="differs from frozen"):
        evaluate_forward_weights(cases)
    cases[-1] = replace(target, observed_at=FIRST - timedelta(days=1))
    with pytest.raises(ValueError, match="published after|frozen before"):
        evaluate_forward_weights(cases)


def test_training_floor_cannot_be_weakened() -> None:
    with pytest.raises(ValueError, match="at least four"):
        evaluate_forward_weights([frozen_case(i) for i in range(5)], minimum_training_races=1)
    with pytest.raises(ValueError, match="insufficient"):
        evaluate_forward_weights([frozen_case(i) for i in range(4)])


def test_report_is_immutable_and_detects_modification(tmp_path: Path) -> None:
    report = evaluate_forward_weights([frozen_case(i) for i in range(7)])
    path = tmp_path / "research-report.json"
    assert write_forward_report(path, report) == path
    assert read_forward_report(path)["reportSha256"] == report.report_sha256
    # Exact same evidence is repeatable, but historical metrics cannot be rewritten.
    write_forward_report(path, report)
    document = json.loads(path.read_text())
    document["pairedSummary"]["pre-race"]["winnerHitRate"] = 1.0
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="digest"):
        read_forward_report(path)
    with pytest.raises(ValueError, match="digest"):
        write_forward_report(path, report)
