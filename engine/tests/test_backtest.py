"""Backtest contract tests — known metrics, typed skips, evidence record.

Spec row "Backtest": expanding-window over the target season; winner hit
rate, podium@3, and Brier reported per model and for the ensemble; the
aggregate joins the ledger as a backtest evidence record. The scoring kernel
is pinned by pure known-value tests (no model, no dataset); the runner is
exercised through the real pipeline on the predictable mini snapshot, whose
finish orders make m3-form's winner pick derivable by hand.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from f1engine.backtest import (
    ENSEMBLE_KEY,
    METRIC_DEFINITIONS,
    BacktestResult,
    BacktestRound,
    RoundScores,
    aggregate_rounds,
    run_backtest,
    score_round,
)
from f1engine.ensemble import Consensus, EnsembleVerdict
from f1engine.evidence import (
    BacktestMetrics,
    append_record,
    build_backtest_record,
    verify_chain,
)
from f1engine.ingestion import PinnedDataset, load_snapshot

WEIGHTS = {"m1-gbm": 1.0, "m2-logit": 1.0, "m3-form": 1.0}
EVIDENCE_BASIS = "REAL MODELS — PINNED DATASET 2020–2024 — NO LIVE INFERENCE"


class TestScoringKnownValues:
    def test_perfect_prediction_scores_zero_brier_and_hits(self) -> None:
        scores = score_round({"a": 1.0}, {"a": 0.9, "b": 0.8, "c": 0.1}, "a", ("a", "b", "c"))
        assert scores.winner_hit is True
        assert scores.podium_hit is True
        assert scores.brier == 0.0

    def test_coinflip_miss_scores_known_brier(self) -> None:
        winner = {"a": 0.5, "b": 0.5}
        scores = score_round(winner, winner, "b", ("a", "b", "x"))
        assert scores.winner_hit is False
        assert scores.podium_hit is False  # fewer than three classified
        assert scores.brier == pytest.approx(0.5)  # (0.5-0)^2 + (0.5-1)^2

    def test_podium_ties_break_by_driver_id(self) -> None:
        podium = {"d": 0.1, "a": 0.5, "c": 0.5, "b": 0.5}
        pick = score_round({"a": 1.0}, podium, "a", ("a", "b", "c"))
        assert pick.podium_hit is True  # a, b, c — d loses the tie-break

    def test_podium_set_mismatch_is_a_miss(self) -> None:
        podium = {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.6}
        scores = score_round({"a": 1.0}, podium, "a", ("a", "b", "d"))
        assert scores.podium_hit is False

    def test_brier_is_never_negative(self) -> None:
        scores = score_round({"a": 0.3, "b": 0.7}, {"a": 0.3, "b": 0.7}, "a", ("a", "b", "c"))
        assert scores.brier >= 0.0


def _scores_round(
    key: str, winner_hit: bool, podium_hit: bool, brier: float
) -> BacktestRound:
    """A minimal BacktestRound carrying one scored key for aggregation tests."""
    return BacktestRound(
        season=2021,
        round_number=1,
        race_id="r",
        predictions=(),
        verdict=EnsembleVerdict(
            race_id="r",
            winner={"a": 1.0},
            podium={"a": 1.0},
            consensus=Consensus(podium_spread=0.0, flag="OK"),
            weights_used={},
        ),
        actual_winner="a",
        actual_podium=("a", "b", "c"),
        scores={
            key: RoundScores(
                winner_hit=winner_hit, podium_hit=podium_hit, brier=brier
            )
        },
        model_duration_ms={},
    )


class TestAggregationKnownValues:
    def test_two_rounds_one_hit_gives_half(self) -> None:
        first = _scores_round("m3-form", True, True, 0.2)
        second = _scores_round("m3-form", False, False, 0.6)
        metrics = aggregate_rounds([first, second])
        assert metrics["m3-form"].rounds == 2
        assert metrics["m3-form"].winner_hit_rate == pytest.approx(0.5)
        assert metrics["m3-form"].podium3_hit_rate == pytest.approx(0.5)
        assert metrics["m3-form"].mean_brier == pytest.approx(0.4)

    def test_unknown_aggregate_key_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown key"):
            aggregate_rounds([_scores_round("m99", True, True, 0.0)])

    def test_empty_backtest_cannot_aggregate(self) -> None:
        with pytest.raises(ValueError, match="no scoreable rounds"):
            aggregate_rounds([])


class TestExpandingWindowRunner:
    @pytest.fixture()
    def result(self, predictable_snapshot: Path) -> BacktestResult:
        dataset = load_snapshot(predictable_snapshot)
        return run_backtest(dataset, target_season=2021, weights=WEIGHTS)

    def test_degenerate_rounds_skipped_typed_rest_scored(
        self, result: BacktestResult
    ) -> None:
        # Rounds 1-3 cannot support a model: round 1 has no prior training
        # data at all, rounds 2-3 only single-class winner labels — typed
        # skips. Rounds 4-5 carry both classes and classified results — scored.
        assert [skip.round for skip in result.skipped] == [1, 2, 3]
        assert all(skip.code == "TRAINING_DATA_INSUFFICIENT" for skip in result.skipped)
        assert [entry.round_number for entry in result.rounds] == [4, 5]

    def test_form_model_hits_known_winners(self, result: BacktestResult) -> None:
        # finish_orders make test-driver the round-4 and round-5 winner, and
        # the rolling-form heuristic's lowest score lands on test-driver too.
        assert result.rounds[0].actual_winner == "test-driver"
        assert result.rounds[0].scores["m3-form"].winner_hit is True
        metrics = aggregate_rounds(result.rounds)
        assert metrics["m3-form"].winner_hit_rate == 1.0
        assert metrics["m3-form"].podium3_hit_rate == 1.0  # three-driver field

    def test_metrics_are_finite_and_bounded(self, result: BacktestResult) -> None:
        metrics = aggregate_rounds(result.rounds)
        assert set(metrics) == {"m1-gbm", "m2-logit", "m3-form", ENSEMBLE_KEY}
        for entry in metrics.values():
            assert entry.rounds == 2
            assert 0.0 <= entry.winner_hit_rate <= 1.0
            assert 0.0 <= entry.podium3_hit_rate <= 1.0
            assert 0.0 <= entry.mean_brier <= 2.0
            assert math.isfinite(entry.mean_brier)

    def test_durations_are_telemetry_not_predictions(
        self, result: BacktestResult
    ) -> None:
        for backtest_round in result.rounds:
            assert set(backtest_round.model_duration_ms) == {
                "m1-gbm",
                "m2-logit",
                "m3-form",
            }
            for duration in backtest_round.model_duration_ms.values():
                assert duration >= 0.0
        # And none of it leaks into the serialized predictions:
        serialized = json.dumps(
            backtest_round.predictions[0].model_dump(by_alias=True)
        )
        assert "durationMs" not in serialized


class TestBacktestEvidenceRecord:
    def test_backtest_record_appends_and_verifies(
        self, predictable_snapshot: Path, tmp_path: Path
    ) -> None:
        dataset = load_snapshot(predictable_snapshot)
        result = run_backtest(dataset, target_season=2021, weights=WEIGHTS)
        record = build_backtest_record(
            dataset,
            season=2021,
            first_round=4,
            last_round=5,
            metrics=aggregate_rounds(result.rounds),
            metric_definitions=METRIC_DEFINITIONS,
            skipped_rounds=result.skipped,
            evidence_basis=EVIDENCE_BASIS,
        )

        assert record.record_type == "backtest"
        assert record.backtest_id == "backtest-2021"
        assert record.advisory_only is True
        assert record.data_limitations == list(dataset.limitations)
        assert set(record.metric_definitions) == set(METRIC_DEFINITIONS)
        assert record.rounds_scored == 2

        ledger = tmp_path / "ledger.jsonl"
        append_record(ledger, record)
        verify_chain(ledger)  # does not raise — backtest records chain like any other

    def test_backtest_record_refuses_unknown_metrics_key(
        self, predictable_snapshot: Path
    ) -> None:
        dataset: PinnedDataset = load_snapshot(predictable_snapshot)
        bogus = BacktestMetrics(
            rounds=1, winner_hit_rate=0.0, podium3_hit_rate=0.0, mean_brier=0.0
        )
        with pytest.raises(Exception, match="unknown key"):
            build_backtest_record(
                dataset,
                season=2021,
                first_round=1,
                last_round=5,
                metrics={"m99": bogus},
                metric_definitions=METRIC_DEFINITIONS,
                skipped_rounds=(),
                evidence_basis=EVIDENCE_BASIS,
            )
