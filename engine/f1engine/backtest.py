"""Expanding-window backtest — measured accuracy against actual results.

Contract (spec, "What 'works' means" row: Backtest): for each target round N
of the backtest season, train every model on rounds strictly before N, predict
N through ingestion -> features -> models -> ensemble, and score the
distributions against what actually happened — winner hit rate, podium@3 hit
rate, and the mean multi-class Brier score of the winner distribution, per
model AND for the ensemble. The aggregate joins the ledger as a backtest
evidence record (evidence.BacktestRecord), so measured accuracy is evidence,
not a console claim.

Determinism contract: every input here is the pinned dataset and fixed seeds —
no wall-clock value enters any stored record. Latency measurement happens in
the runner (durationMs was deliberately absent from ModelPrediction), stays in
memory, and only ever reaches the observability bus via the demo orchestrator.

Scoring definitions (also serialized into the backtest record, so the record
self-describes what its numbers mean):
  winner_hit_rate — fraction of scored rounds where the distribution's
      highest-probability driver is the classified first-place finisher.
      Equal probabilities break by driver id — deterministic by construction.
  podium3_hit_rate — fraction of scored rounds where the three highest
      P(top-3) drivers equal the three classified top finishers. Fewer than
      three classified finishers in a round scores a miss.
  mean_brier — mean over scored rounds of the multi-class Brier score of the
      winner distribution against the actual one-hot winner.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from f1engine.ensemble import EnsembleVerdict, ModelWeights, arbitrate
from f1engine.evidence import ENSEMBLE_KEY, BacktestMetrics, SkippedRound
from f1engine.features import build_asof_features
from f1engine.ingestion import PinnedDataset
from f1engine.models import (
    MODEL_IDS,
    InsufficientTrainingData,
    ModelPrediction,
    PredictionModel,
    create_models,
)

WINNER_HIT_RATE_DEFINITION = (
    "fraction of scored rounds where the distribution's highest-probability "
    "driver is the classified first-place finisher (ties break by driver id)"
)
PODIUM3_HIT_RATE_DEFINITION = (
    "fraction of scored rounds where the three highest P(top-3) drivers equal "
    "the three classified top finishers; fewer than three classified "
    "finishers scores a miss"
)
MEAN_BRIER_DEFINITION = (
    "mean over scored rounds of the multi-class Brier score of the winner "
    "distribution against the actual one-hot winner"
)
METRIC_DEFINITIONS: dict[str, str] = {
    "winner_hit_rate": WINNER_HIT_RATE_DEFINITION,
    "podium3_hit_rate": PODIUM3_HIT_RATE_DEFINITION,
    "mean_brier": MEAN_BRIER_DEFINITION,
}


@dataclass(frozen=True)
class RoundScores:
    """One distribution set scored against one round's actual result."""

    winner_hit: bool
    podium_hit: bool
    brier: float


@dataclass(frozen=True)
class BacktestRound:
    """Everything one target round contributes to the backtest."""

    season: int
    round_number: int
    race_id: str
    predictions: tuple[ModelPrediction, ...]
    verdict: EnsembleVerdict
    actual_winner: str
    actual_podium: tuple[str, ...]
    scores: dict[str, RoundScores]  # per model id, plus "ensemble"
    model_duration_ms: dict[str, float]  # wall-clock telemetry — never stored


@dataclass(frozen=True)
class BacktestResult:
    """The full expanding-window run: scored rounds plus typed skips."""

    target_season: int
    rounds: tuple[BacktestRound, ...]
    skipped: tuple[SkippedRound, ...]


def score_round(
    winner: dict[str, float],
    podium: dict[str, float],
    actual_winner: str,
    actual_podium: tuple[str, ...],
) -> RoundScores:
    """Score one distribution set against one round's classified result.

    Pure function — the known-value tests pin these semantics independently
    of any model or dataset. Rankings sort by descending probability with
    driver-id tie-breaks, so equal probabilities stay deterministic.
    """
    winner_pick = min(
        winner, key=lambda driver_id: (-winner[driver_id], driver_id)
    ) if winner else None
    podium_pick = {
        driver_id
        for driver_id, _ in sorted(podium.items(), key=lambda item: (-item[1], item[0]))[:3]
    }
    brier = sum(
        (probability - (1.0 if driver_id == actual_winner else 0.0)) ** 2
        for driver_id, probability in winner.items()
    )
    return RoundScores(
        winner_hit=winner_pick == actual_winner,
        podium_hit=len(actual_podium) == 3 and podium_pick == set(actual_podium),
        brier=brier,
    )


@dataclass(frozen=True)
class ClassifiedResult:
    """One round's classified result, exactly as the backtest scores it.

    The single classification of "what actually happened": the winner, the
    podium@3 actual (first three classified — shorter when fewer finished),
    and the full classified finishing order (P4 lives at index 3, which the
    game's near-miss rule needs). The game scoring module consumes this type
    rather than re-deriving results — one source of truth.
    """

    winner: str
    podium: tuple[str, ...]
    classified: tuple[str, ...]


def classify_round(entries: Iterable[tuple[int | None, str]]) -> ClassifiedResult | None:
    """Classify one round's result entries; None when no classified winner.

    Entries are (classified position, driver id); None positions (DNFs,
    unclassified runners) are excluded, and a round whose best classified
    position is not 1 has no winner to score against. Public so the game
    scoring and the /result endpoint classify exactly as run_backtest does.
    """
    classified = sorted(entry for entry in entries if entry[0] is not None)
    if not classified or classified[0][0] != 1:
        return None
    order = tuple(driver_id for _, driver_id in classified)
    return ClassifiedResult(winner=order[0], podium=order[:3], classified=order)


def _actuals(
    dataset: PinnedDataset,
) -> dict[tuple[int, int], tuple[str, tuple[str, ...]]]:
    """Classified winner and podium per round, from the results table."""
    entries_by_round: dict[tuple[int, int], list[tuple[int | None, str]]] = {}
    for row in dataset.results:
        entries_by_round.setdefault((row.season, row.round), []).append(
            (row.position, row.driver_id)
        )
    scored: dict[tuple[int, int], tuple[str, tuple[str, ...]]] = {}
    for key, entries in entries_by_round.items():
        result = classify_round(entries)
        if result is not None:
            scored[key] = (result.winner, result.podium)
    return scored


def run_backtest(
    dataset: PinnedDataset,
    *,
    target_season: int,
    weights: ModelWeights,
) -> BacktestResult:
    """Expanding-window backtest over one season's scoreable rounds.

    For every round of ``target_season`` that has a classified winner, all
    three models train on rounds strictly before it (fixed seeds), predict it,
    and the ensemble arbitrates; the round is scored against the actual
    result. A round whose training window cannot support a model (single-class
    labels on tiny datasets) is recorded as a typed skip — visible in the
    backtest record, never silently dropped. Rounds without classified
    results are not backtest targets at all: there is nothing to score
    against, and this docstring declares that filter.
    """
    table = build_asof_features(dataset)
    actuals = _actuals(dataset)

    target_keys = sorted(key for key in actuals if key[0] == target_season)
    rounds: list[BacktestRound] = []
    skipped: list[SkippedRound] = []
    for season, round_number in target_keys:
        as_of = (season, round_number)
        models = create_models()
        try:
            for model in models.values():
                model.train(dataset, table, as_of)
        except InsufficientTrainingData as error:
            skipped.append(
                SkippedRound(
                    season=season,
                    round=round_number,
                    code=error.code,
                    message=str(error),
                )
            )
            continue

        predictions, durations = _predict_all(models, season, round_number)
        verdict = arbitrate(predictions, weights)
        actual_winner, actual_podium = actuals[as_of]
        scores: dict[str, RoundScores] = {
            prediction.model_id: score_round(
                prediction.winner, prediction.podium, actual_winner, actual_podium
            )
            for prediction in predictions
        }
        scores[ENSEMBLE_KEY] = score_round(
            verdict.winner, verdict.podium, actual_winner, actual_podium
        )
        rounds.append(
            BacktestRound(
                season=season,
                round_number=round_number,
                race_id=predictions[0].race_id,
                predictions=predictions,
                verdict=verdict,
                actual_winner=actual_winner,
                actual_podium=actual_podium,
                scores=scores,
                model_duration_ms=durations,
            )
        )
    return BacktestResult(
        target_season=target_season, rounds=tuple(rounds), skipped=tuple(skipped)
    )


def _predict_all(
    models: dict[str, PredictionModel], season: int, round_number: int
) -> tuple[tuple[ModelPrediction, ...], dict[str, float]]:
    """Predict one round with every model, timing each (telemetry only)."""
    predictions: list[ModelPrediction] = []
    durations: dict[str, float] = {}
    for model_id, model in models.items():
        started = time.perf_counter()
        prediction = model.predict(season, round_number)
        durations[model_id] = (time.perf_counter() - started) * 1000.0
        predictions.append(prediction)
    return tuple(predictions), durations


def aggregate_rounds(rounds: Sequence[BacktestRound]) -> dict[str, BacktestMetrics]:
    """Fold per-round scores into per-model/ensemble aggregate metrics."""
    if not rounds:
        raise ValueError("backtest produced no scoreable rounds — nothing to aggregate")
    per_key: dict[str, list[RoundScores]] = {}
    for backtest_round in rounds:
        for key, scores in backtest_round.scores.items():
            per_key.setdefault(key, []).append(scores)
    return {
        key: _aggregate_scores(key, scored_rounds)
        for key, scored_rounds in sorted(per_key.items())
    }


def _aggregate_scores(key: str, scored_rounds: list[RoundScores]) -> BacktestMetrics:
    if key not in MODEL_IDS and key != ENSEMBLE_KEY:
        raise ValueError(f"aggregate scored under unknown key {key!r}")
    count = len(scored_rounds)
    return BacktestMetrics(
        rounds=count,
        winner_hit_rate=sum(s.winner_hit for s in scored_rounds) / count,
        podium3_hit_rate=sum(s.podium_hit for s in scored_rounds) / count,
        mean_brier=sum(s.brier for s in scored_rounds) / count,
    )
