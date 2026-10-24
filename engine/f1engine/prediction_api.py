"""Pre-race prediction read model: catalog, typed envelope, evaluation.

This is a read view over what the engine has actually produced. It adds no
new model and invents no value:

* The models build every feature from rounds strictly *before* the target
  round (features.py), so the existing predictions are a **pre-weekend**
  checkpoint. A post-qualifying checkpoint is reported as unsupported until a
  model that reads the round's own qualifying is trained and evaluated.
* The pinned snapshot holds completed seasons only, so every prediction here
  is a **historical backtest**: replayed from the ledger, never presented as
  a forecast of an upcoming race.
* Winner probabilities are served. Podium values are checked for coherence
  (three podium places means the field should sum to about 3); stored
  podium values fail it for many races and have no independent evaluation, so
  podium is reported as unsupported for every race.

Real-world timestamps (`fetchedAt`, `sourceUpdatedAt`) are kept apart from the
deterministic evidence identifier (`evidenceGeneratedAt`), which is the
snapshot's provenance time and is not the moment a forecast was made.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median
from typing import Literal

from f1engine.evidence import PredictionRecord
from f1engine.features import AsOfFeatureRow, build_asof_features
from f1engine.ingestion import PinnedDataset, RaceRow
from f1engine.models import FEATURE_COLUMNS, MODEL_IDS, MODEL_SEED
from f1engine.wire import WireModel

Checkpoint = Literal["pre-weekend", "post-qualifying"]
CHECKPOINTS: tuple[Checkpoint, ...] = ("pre-weekend", "post-qualifying")
PredictionMode = Literal["historical-backtest", "pre-race", "unavailable"]

PODIUM_SUM_TOLERANCE = 0.15
MIN_WINNERS_FOR_CALIBRATION = 200
WINNER_SUM_TOLERANCE = 1e-6

FEATURE_LABELS: dict[str, str] = {
    "starts": "Prior race starts in the snapshot",
    "form_finish_mean": "Average finish, last five rounds",
    "form_finish_mean_all": "Average finish, all prior rounds",
    "q_best_ms": "Best qualifying lap, last five rounds (ms)",
    "q_delta_teammate_ms": "Qualifying gap to teammate, last five rounds (ms)",
    "q_delta_pole_ms": "Qualifying gap to pole, last five rounds (ms)",
    "team_points_mean": "Team points per round, prior rounds",
    "track_finish_mean": "Average finish at this race, earlier seasons",
}
# For these features a smaller number is better (finish places, gaps).
_LOWER_IS_BETTER = frozenset(
    {
        "form_finish_mean",
        "form_finish_mean_all",
        "q_best_ms",
        "q_delta_teammate_ms",
        "q_delta_pole_ms",
        "track_finish_mean",
    }
)


class PredictionUnavailable(LookupError):
    """A race exists but has no servable prediction for the checkpoint."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------- wire


class CheckpointSupport(WireModel):
    checkpoint: Checkpoint
    supported: bool
    reason: str | None = None


class CatalogRace(WireModel):
    race_id: str
    season: int
    round: int
    name: str
    race_date: str
    circuit_name: str
    country: str
    status: Literal["completed", "upcoming"]
    prediction_mode: PredictionMode
    checkpoints: list[CheckpointSupport]


class PredictionCatalogView(WireModel):
    races: list[CatalogRace]
    total: int
    supported_total: int
    dataset_id: str
    dataset_digest: str
    data_through_date: str
    upcoming_races: int
    upcoming_note: str
    advisory_only: Literal[True] = True


class FeatureCutoff(WireModel):
    """The last data a pre-weekend prediction may read."""

    through_season: int | None
    through_round: int | None
    through_race_name: str | None
    through_race_date: str | None
    excludes: list[str]


class DriverForecast(WireModel):
    driver_id: str
    driver_name: str
    driver_code: str
    constructor_id: str
    constructor_name: str
    rank: int
    win_probability: float
    per_model_win_probability: dict[str, float]
    features: dict[str, float | None]
    reasons: list[str]


class OutputSupport(WireModel):
    output: Literal["winner", "podium", "points", "finishPosition", "dnfRisk", "intervals"]
    supported: bool
    reason: str


class MissingInput(WireModel):
    input: str
    status: Literal["not-used-by-model", "not-in-dataset"]
    detail: str
    source_needed: str


class ValidationCheck(WireModel):
    check: str
    passed: bool
    detail: str


class SourceRef(WireModel):
    provider: str
    role: str
    fetched_at: str | None
    license: str


class Baseline(WireModel):
    name: str
    win_probability: float
    detail: str


class PredictionEnvelope(WireModel):
    race_id: str
    season: int
    round: int
    race_name: str
    race_date: str
    circuit_name: str
    country: str
    session: Literal["race"] = "race"
    prediction_mode: Literal["historical-backtest"]
    checkpoint: Checkpoint
    prediction_generated_at: str | None
    evidence_generated_at: str
    feature_cutoff: FeatureCutoff
    source_updated_at: str
    fetched_at: str
    freshness: Literal["historical"]
    freshness_note: str
    model_revision: str
    models: list[str]
    dataset_id: str
    dataset_digest: str
    evidence_prediction_id: str
    provenance: list[SourceRef]
    outputs: list[OutputSupport]
    drivers: list[DriverForecast]
    feature_labels: dict[str, str]
    consensus_flag: str
    baseline: Baseline
    missing_inputs: list[MissingInput]
    limitations: list[str]
    validation: list[ValidationCheck]
    outcome_available: bool
    advisory_only: Literal[True] = True


class MetricEstimate(WireModel):
    value: float
    ci_low: float
    ci_high: float


class ModelScore(WireModel):
    model_id: str
    rounds: int
    winner_hit_rate: MetricEstimate
    winner_log_loss: MetricEstimate
    winner_brier: MetricEstimate
    mean_probability_on_winner: float


class CalibrationBin(WireModel):
    lower: float
    upper: float
    predictions: int
    mean_predicted: float | None
    observed_win_rate: float | None


class ModelEvaluationView(WireModel):
    cohort: str
    method: str
    rounds: int
    season: int | None
    scores: list[ModelScore]
    baseline: ModelScore
    calibration_model: str
    calibration: list[CalibrationBin]
    calibration_verdict: str
    caveats: list[str]
    bootstrap_resamples: int
    bootstrap_seed: int
    advisory_only: Literal[True] = True


# -------------------------------------------------------------------- logic


@dataclass(frozen=True)
class _Context:
    dataset: PinnedDataset
    records: tuple[PredictionRecord, ...]


def _race_key(race: RaceRow) -> tuple[int, int]:
    return (race.season, race.round)


def _records_by_race(
    records: Sequence[PredictionRecord],
) -> dict[tuple[int, str], PredictionRecord]:
    by_race: dict[tuple[int, str], PredictionRecord] = {}
    for record in records:
        # The ledger is append-only; the latest record for a race wins.
        by_race[(record.race.season, record.race.race_id)] = record
    return by_race


def _post_qualifying_reason() -> str:
    return (
        "The models read only rounds before the race, not that race's own "
        "qualifying. No post-qualifying model has been trained and evaluated."
    )


def build_catalog(
    dataset: PinnedDataset, records: Sequence[PredictionRecord]
) -> PredictionCatalogView:
    by_race = _records_by_race(records)
    completed = {(r.season, r.round) for r in dataset.results}
    races: list[CatalogRace] = []
    for race in sorted(dataset.races, key=_race_key, reverse=True):
        has_record = (race.season, race.race_id) in by_race
        status: Literal["completed", "upcoming"] = (
            "completed" if _race_key(race) in completed else "upcoming"
        )
        if has_record and status == "completed":
            mode: PredictionMode = "historical-backtest"
            pre = CheckpointSupport(checkpoint="pre-weekend", supported=True)
        else:
            mode = "unavailable"
            pre = CheckpointSupport(
                checkpoint="pre-weekend",
                supported=False,
                reason=(
                    "No prediction record for this round in the evidence ledger. "
                    "Running the backtest for its season would produce one."
                    if status == "completed"
                    else "Upcoming races need a verified entry list and a current-season "
                    "data refresh before a prediction can be made."
                ),
            )
        races.append(
            CatalogRace(
                race_id=race.race_id,
                season=race.season,
                round=race.round,
                name=race.name,
                race_date=race.date,
                circuit_name=race.circuit_name,
                country=race.country,
                status=status,
                prediction_mode=mode,
                checkpoints=[
                    pre,
                    CheckpointSupport(
                        checkpoint="post-qualifying",
                        supported=False,
                        reason=_post_qualifying_reason(),
                    ),
                ],
            )
        )
    upcoming = sum(1 for race in races if race.status == "upcoming")
    return PredictionCatalogView(
        races=races,
        total=len(races),
        supported_total=sum(1 for race in races if race.prediction_mode != "unavailable"),
        dataset_id=dataset.dataset_id,
        dataset_digest=dataset.dataset_sha256,
        data_through_date=max(race.date for race in dataset.races),
        upcoming_races=upcoming,
        upcoming_note=(
            "No upcoming races are in the pinned data. Current-season predictions "
            "need a verified calendar, entry list and results refresh from the "
            "licensed provider (scripts/refresh-data.py)."
            if upcoming == 0
            else "Upcoming races are listed but have no supported prediction yet."
        ),
    )


def _feature_cutoff(dataset: PinnedDataset, race: RaceRow) -> FeatureCutoff:
    earlier = [r for r in dataset.races if _race_key(r) < _race_key(race)]
    previous = max(earlier, key=_race_key) if earlier else None
    return FeatureCutoff(
        through_season=previous.season if previous else None,
        through_round=previous.round if previous else None,
        through_race_name=previous.name if previous else None,
        through_race_date=previous.date if previous else None,
        excludes=[
            "This race's practice, qualifying, grid and penalties",
            "This race's result and anything later",
        ],
    )


_FEATURE_TABLES: dict[str, list[AsOfFeatureRow]] = {}


def _features_for(dataset: PinnedDataset, race: RaceRow) -> dict[str, AsOfFeatureRow]:
    # The as-of table depends only on the pinned dataset; build it once per digest.
    if dataset.dataset_sha256 not in _FEATURE_TABLES:
        _FEATURE_TABLES[dataset.dataset_sha256] = list(build_asof_features(dataset).rows)
    table_rows = _FEATURE_TABLES[dataset.dataset_sha256]
    return {row.driver_id: row for row in table_rows if (row.season, row.round) == _race_key(race)}


def _reasons(driver: AsOfFeatureRow, field: Sequence[AsOfFeatureRow]) -> list[str]:
    """Deterministic, feature-grounded notes: where this driver ranks in the field."""
    notes: list[tuple[int, str]] = []
    for name in ("form_finish_mean", "team_points_mean", "q_delta_pole_ms", "track_finish_mean"):
        value = getattr(driver, name)
        values = [getattr(row, name) for row in field if getattr(row, name) is not None]
        if value is None or len(values) < 3:
            continue
        ordered = sorted(values, reverse=name not in _LOWER_IS_BETTER)
        rank = ordered.index(value) + 1
        if rank <= 3:
            label = FEATURE_LABELS[name].removesuffix(" (ms)").lower()
            shown = f"{value:,.0f} ms" if name.endswith("_ms") else f"{value:.1f}"
            joint = "joint " if values.count(value) > 1 else ""
            notes.append(
                (rank, f"Ranks {joint}{rank} of {len(values)} on {label} ({shown}).")
            )
    if driver.starts < 5:
        notes.append((0, f"Only {driver.starts} prior starts in the data, so form is thin."))
    return [text for _, text in sorted(notes)][:3]


def _validate(record: PredictionRecord, entrants: set[str]) -> tuple[list[ValidationCheck], bool]:
    checks: list[ValidationCheck] = []
    distributions = {"ensemble": record.ensemble.winner} | {
        model_id: prediction.winner for model_id, prediction in record.models.items()
    }
    for name, values in distributions.items():
        total = sum(values.values())
        in_range = all(0.0 <= p <= 1.0 and math.isfinite(p) for p in values.values())
        checks.append(
            ValidationCheck(
                check=f"{name} winner probabilities sum to 1",
                passed=in_range and math.isclose(total, 1.0, abs_tol=WINNER_SUM_TOLERANCE),
                detail=f"sum = {total:.6f}; all values in [0, 1]: {in_range}",
            )
        )
    covered = set(record.ensemble.winner)
    checks.append(
        ValidationCheck(
            check="every entrant has a winner probability",
            passed=covered == entrants,
            detail=f"{len(covered)} drivers with probabilities, {len(entrants)} entrants",
        )
    )
    podium_total = sum(record.ensemble.podium.values())
    podium_ok = abs(podium_total - 3.0) <= PODIUM_SUM_TOLERANCE
    checks.append(
        ValidationCheck(
            check="podium probabilities sum to about 3",
            passed=podium_ok,
            detail=f"ensemble sum = {podium_total:.2f} (needs 3 ± {PODIUM_SUM_TOLERANCE})",
        )
    )
    return checks, podium_ok


def build_envelope(
    dataset: PinnedDataset,
    records: Sequence[PredictionRecord],
    race: RaceRow,
    checkpoint: Checkpoint,
    *,
    now: datetime | None = None,
) -> PredictionEnvelope:
    if checkpoint == "post-qualifying":
        raise PredictionUnavailable("CHECKPOINT_UNSUPPORTED", _post_qualifying_reason())
    record = _records_by_race(records).get((race.season, race.race_id))
    if record is None:
        raise PredictionUnavailable(
            "PREDICTION_UNAVAILABLE",
            f"No prediction record for {race.season} {race.name} in the evidence ledger.",
        )
    results = [r for r in dataset.results if (r.season, r.round) == _race_key(race)]
    entrants = {r.driver_id: r.constructor_id for r in results}
    features = _features_for(dataset, race)
    drivers_by_id = {d.driver_id: d for d in dataset.drivers}
    teams_by_id = {c.constructor_id: c for c in dataset.constructors}

    checks, podium_ok = _validate(record, set(entrants))
    winner = record.ensemble.winner
    ordered = sorted(winner, key=lambda driver: (-winner[driver], driver))
    field = list(features.values())
    forecasts: list[DriverForecast] = []
    for rank, driver_id in enumerate(ordered, start=1):
        driver = drivers_by_id.get(driver_id)
        constructor_id = entrants.get(driver_id, "unknown")
        team = teams_by_id.get(constructor_id)
        row = features.get(driver_id)
        forecasts.append(
            DriverForecast(
                driver_id=driver_id,
                driver_name=f"{driver.given_name} {driver.family_name}" if driver else driver_id,
                driver_code=driver.code if driver else driver_id[:3].upper(),
                constructor_id=constructor_id,
                constructor_name=team.name if team else constructor_id,
                rank=rank,
                win_probability=winner[driver_id],
                per_model_win_probability={
                    model_id: record.models[model_id].winner.get(driver_id, 0.0)
                    for model_id in record.models
                },
                features={name: getattr(row, name) for name in FEATURE_COLUMNS} if row else {},
                reasons=_reasons(row, field) if row else [],
            )
        )

    when = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    provenance = dataset.provenance
    return PredictionEnvelope(
        race_id=race.race_id,
        season=race.season,
        round=race.round,
        race_name=race.name,
        race_date=race.date,
        circuit_name=race.circuit_name,
        country=race.country,
        prediction_mode="historical-backtest",
        checkpoint=checkpoint,
        prediction_generated_at=None,
        evidence_generated_at=record.generated_at,
        feature_cutoff=_feature_cutoff(dataset, race),
        source_updated_at=provenance.generatedAt,
        fetched_at=when,
        freshness="historical",
        freshness_note=(
            f"Replayed from data retrieved {provenance.generatedAt[:10]}. This race is "
            "finished; the prediction was produced afterward from data available before it."
        ),
        model_revision=f"{'+'.join(MODEL_IDS)}@seed-{MODEL_SEED}",
        models=list(record.models),
        dataset_id=record.dataset.id,
        dataset_digest=record.dataset.sha256,
        evidence_prediction_id=record.prediction_id,
        provenance=[
            SourceRef(provider=s.provider, role=s.role, fetched_at=s.fetchedAt, license=s.license)
            for s in provenance.sources
            if s.fetchedAt is not None
        ],
        outputs=[
            OutputSupport(
                output="winner",
                supported=True,
                reason="Ensemble of three models; sums to 1 across the field.",
            ),
            OutputSupport(
                output="podium",
                supported=False,
                reason=(
                    "Stored podium values are independent per driver and do not add up "
                    "to three podium places, so they are not shown."
                    if not podium_ok
                    else "Podium values are coherent for this race but have no independent "
                    "evaluation yet."
                ),
            ),
            OutputSupport(
                output="points", supported=False, reason="No points model has been trained."
            ),
            OutputSupport(
                output="finishPosition",
                supported=False,
                reason="No finishing-order distribution has been validated.",
            ),
            OutputSupport(
                output="dnfRisk", supported=False, reason="No retirement model has been trained."
            ),
            OutputSupport(
                output="intervals",
                supported=False,
                reason="Uncertainty intervals for single predictions are not validated.",
            ),
        ],
        drivers=forecasts,
        feature_labels=dict(FEATURE_LABELS),
        consensus_flag=record.ensemble.consensus.flag,
        baseline=Baseline(
            name="Blind guess",
            win_probability=1.0 / len(winner),
            detail=f"Picking any of the {len(winner)} entrants at random.",
        ),
        missing_inputs=[
            MissingInput(
                input="Qualifying and grid for this race",
                status="not-used-by-model",
                detail="The pre-weekend checkpoint is fixed before qualifying.",
                source_needed="A post-qualifying model and timestamped qualifying results",
            ),
            MissingInput(
                input="Weather forecast",
                status="not-in-dataset",
                detail="No forecast weather is stored; observed race weather must not be used.",
                source_needed="An archived pre-race forecast provider",
            ),
            MissingInput(
                input="Practice pace and tire data",
                status="not-in-dataset",
                detail="No practice sessions are in the pinned snapshot.",
                source_needed="Licensed session timing (OpenF1)",
            ),
            MissingInput(
                input="Grid penalties",
                status="not-in-dataset",
                detail="Penalties are not recorded separately in the snapshot.",
                source_needed="Official stewards' decisions with timestamps",
            ),
        ],
        limitations=[
            *record.data_limitations,
            "The entrant list comes from the race's classified results; pre-race entry lists "
            "are not in the snapshot.",
            "Winner probabilities are not shown to be calibrated; see Model Performance.",
        ],
        validation=checks,
        outcome_available=bool(results),
    )


# ---------------------------------------------------------------- evaluation


def _bootstrap(values: Sequence[float], *, resamples: int, seed: int) -> MetricEstimate:
    mean = sum(values) / len(values)
    rng = random.Random(seed)
    stats = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(resamples))
    low = stats[int(0.025 * (resamples - 1))]
    high = stats[int(0.975 * (resamples - 1))]
    return MetricEstimate(value=mean, ci_low=low, ci_high=high)


def evaluate_winners(
    dataset: PinnedDataset,
    records: Sequence[PredictionRecord],
    *,
    resamples: int = 2000,
    seed: int = MODEL_SEED,
) -> ModelEvaluationView:
    """Score stored walk-forward winner probabilities against classified winners."""
    winners = {(r.season, r.race_id): r.driver_id for r in dataset.results if r.position == 1}
    scored = [
        record
        for record in _records_by_race(records).values()
        if (record.race.season, record.race.race_id) in winners
    ]
    scored.sort(key=lambda record: (record.race.season, record.race.round))
    seasons = {record.race.season for record in scored}

    def score(name: str, distribution_of) -> tuple[ModelScore, list[tuple[float, bool]]]:
        hits, losses, briers, on_winner = [], [], [], []
        pairs: list[tuple[float, bool]] = []
        for record in scored:
            dist = distribution_of(record)
            actual = winners[(record.race.season, record.race.race_id)]
            p_actual = dist.get(actual, 0.0)
            # A tie at the top shares the hit: k tied favorites earn 1/k each.
            best = max(dist.values())
            tied = [d for d, p in dist.items() if p == best]
            hits.append(1.0 / len(tied) if actual in tied else 0.0)
            losses.append(-math.log(max(p_actual, 1e-15)))
            briers.append(
                sum((p - (1.0 if d == actual else 0.0)) ** 2 for d, p in dist.items())
                + (0.0 if actual in dist else 1.0)
            )
            on_winner.append(p_actual)
            pairs.extend((p, d == actual) for d, p in dist.items())
        return ModelScore(
            model_id=name,
            rounds=len(scored),
            winner_hit_rate=_bootstrap(hits, resamples=resamples, seed=seed),
            winner_log_loss=_bootstrap(losses, resamples=resamples, seed=seed),
            winner_brier=_bootstrap(briers, resamples=resamples, seed=seed),
            mean_probability_on_winner=sum(on_winner) / len(on_winner),
        ), pairs

    if not scored:
        raise PredictionUnavailable("EVALUATION_UNAVAILABLE", "No scored prediction records.")
    model_scores: list[ModelScore] = []
    ensemble_pairs: list[tuple[float, bool]] = []
    for model_id in MODEL_IDS:
        result, _ = score(model_id, lambda record, m=model_id: record.models[m].winner)
        model_scores.append(result)
    ensemble, ensemble_pairs = score("ensemble", lambda record: record.ensemble.winner)
    model_scores.append(ensemble)
    baseline, _ = score(
        "blind-guess",
        lambda record: {d: 1.0 / len(record.ensemble.winner) for d in record.ensemble.winner},
    )

    edges = (0.0, 0.05, 0.1, 0.2, 0.4, 1.0)
    bins: list[CalibrationBin] = []
    for lower, upper in zip(edges, edges[1:], strict=False):
        inside = [
            (p, won)
            for p, won in ensemble_pairs
            if lower <= p < upper or (upper == 1.0 and p == 1.0)
        ]
        bins.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                predictions=len(inside),
                mean_predicted=(sum(p for p, _ in inside) / len(inside)) if inside else None,
                observed_win_rate=(sum(1 for _, won in inside if won) / len(inside))
                if inside
                else None,
            )
        )
    winners_count = len(scored)
    return ModelEvaluationView(
        cohort=", ".join(str(season) for season in sorted(seasons)) + " season prediction records",
        method=(
            "Walk-forward: each stored prediction was trained only on rounds before its race. "
            "Scored here against the classified winner; nothing was re-tuned."
        ),
        rounds=winners_count,
        season=next(iter(seasons)) if len(seasons) == 1 else None,
        scores=model_scores,
        baseline=baseline,
        calibration_model="ensemble",
        calibration=bins,
        calibration_verdict=(
            f"Not established: only {winners_count} race winners. Calibration needs many "
            "more races before the bins mean anything."
            if winners_count < MIN_WINNERS_FOR_CALIBRATION
            else f"Indicative only: {winners_count} race winners across "
            f"{sum(1 for b in bins if b.predictions)} populated bins; compare predicted "
            "and observed columns."
        ),
        caveats=[
            *(
                [f"{winners_count} races is a small sample; the 95% intervals are wide."]
                if winners_count < MIN_WINNERS_FOR_CALIBRATION
                else []
            ),
            "Intervals are a bootstrap over races, not a guarantee for future races.",
            (
                "One season only; results may not carry over to new regulations or teams."
                if len(seasons) == 1
                else f"{len(seasons)} seasons pooled; regulation changes between them "
                "are not modeled."
            ),
        ],
        bootstrap_resamples=resamples,
        bootstrap_seed=seed,
    )


def field_median(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return median(present) if present else None
