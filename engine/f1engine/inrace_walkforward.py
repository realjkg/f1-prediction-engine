"""Forward-only research validation of in-race model blend weights.

The result of the target event is NEVER used in weight selection. A race is
the evaluation unit: exactly one predeclared checkpoint per event is required,
preventing high-frequency lap checkpoints from masquerading as independent
race wins. This is diagnostic research, not automatic model promotion.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from f1engine.inrace_evaluation import FrozenEvaluationCase, _proper_score

# Fixed *before* loading target-event outcomes. Do not optimize this grid on
# later races, or redefine it after reading a reported holdout.
WEIGHT_GRID = tuple(i / 10 for i in range(11))
MIN_TRAINING_RACES = 4
EVALUATION_REVISION = "event-forward-fusion-research-v1"


@dataclass(frozen=True)
class ForwardFold:
    season: int
    race_id: str
    lap: int
    as_of: str
    last_training_result_at: str
    training_races: int
    selected_scenario_weight: float
    target_winner: int
    winner_choices: dict[str, int]
    multiclass_brier: dict[str, float]
    winner_log_loss: dict[str, float]


@dataclass(frozen=True)
class ForwardReport:
    revision: str
    research_only: bool
    model_promotion_allowed: bool
    minimum_training_races: int
    candidate_weights: tuple[float, ...]
    eligible_races: int
    scored_races: int
    unscored_races: int
    folds: tuple[ForwardFold, ...]
    paired_summary: dict[str, dict[str, float]]
    caveats: tuple[str, ...]
    report_sha256: str


def _validate_case(case: FrozenEvaluationCase) -> None:
    if case.observed_at.tzinfo is None or case.result_published_at.tzinfo is None:
        raise ValueError("observation and result-publication times require timezones")
    if case.result_published_at.astimezone(UTC) <= case.observed_at.astimezone(UTC):
        raise ValueError("classified result must be published after target observation")
    scenario, combined = case.scenario, case.combined
    if (
        (scenario.season, scenario.race_id, scenario.checkpoint_lap)
        != (case.season, case.race_id, case.lap)
        or scenario.status != "experimental-scenario-only"
        or combined.checkpoint_sha256 != scenario.checkpoint_record_sha256
        or combined.lap != case.lap
        or combined.status != "unqualified-blend"
        or combined.promoted is not False
    ):
        raise ValueError("scenario and research fusion must bind the same checkpoint")
    if datetime.fromisoformat(
        combined.prior_frozen_at.replace("Z", "+00:00")
    ).astimezone(UTC) >= case.observed_at.astimezone(UTC):
        raise ValueError("pre-race prior must be frozen before the lap cutoff")
    drivers = {v.driver_number for v in scenario.drivers}
    if (
        case.winner_driver_number not in drivers
        or drivers != set(case.initial_prior)
        or drivers != {v.driver_number for v in combined.candidates}
    ):
        raise ValueError("entrant fields must match across all probability sources")
    prior_by_fusion = {c.driver_number: c.pre_race_probability for c in combined.candidates}
    pace_by_fusion = {
        c.driver_number: c.green_continuation_frequency for c in combined.candidates
    }
    pace_by_scenario = {
        d.driver_number: d.conditional_win_frequency for d in scenario.drivers
    }
    if any(
        not math.isclose(prior_by_fusion[k], p, abs_tol=1e-9)
        for k, p in case.initial_prior.items()
    ) or any(
        not math.isclose(pace_by_fusion[k], pace_by_scenario[k], abs_tol=1e-9)
        for k in drivers
    ):
        raise ValueError("stored combination differs from frozen pre-race/lap inputs")
    _proper_score(case.initial_prior, case.winner_driver_number)
    _proper_score(pace_by_scenario, case.winner_driver_number)


def _probabilities(case: FrozenEvaluationCase, weight: float) -> dict[int, float]:
    current = {
        d.driver_number: d.conditional_win_frequency for d in case.scenario.drivers
    }
    return {
        car: (1.0 - weight) * p + weight * current[car]
        for car, p in case.initial_prior.items()
    }


def _choose_weight(previous: list[FrozenEvaluationCase]) -> float:
    """Choose solely on earlier published results, not the target race."""
    best: tuple[float, float, float] | None = None
    for weight in WEIGHT_GRID:
        scores = [
            _proper_score(_probabilities(item, weight), item.winner_driver_number)
            for item in previous
        ]
        mean_brier = sum(score[0] for score in scores) / len(scores)
        mean_logloss = sum(score[1] for score in scores) / len(scores)
        # Prefer less intervention if the proper scoring evidence is tied.
        key = (round(mean_brier, 12), round(mean_logloss, 12), weight)
        if best is None or key < best:
            best = key
    assert best is not None
    return best[2]


def _summarize(
    folds: list[ForwardFold],
) -> dict[str, dict[str, float]]:
    labels = ("pre-race", "running-order", "green-continuation", "walkforward-fusion")
    return {
        label: {
            "races": float(len(folds)),
            "winnerHitRate": sum(
                f.winner_choices[label] == f.target_winner for f in folds
            ) / len(folds),
            "meanMulticlassBrier": sum(
                f.multiclass_brier[label] for f in folds
            ) / len(folds),
            "meanWinnerLogLoss": sum(
                f.winner_log_loss[label] for f in folds
            ) / len(folds),
        }
        for label in labels
    }


def evaluate_forward_weights(
    cases: list[FrozenEvaluationCase], *, minimum_training_races: int = MIN_TRAINING_RACES,
) -> ForwardReport:
    """Walk-forward Brier optimization on earlier races with paired holdout.

    If no prior results are eligible for a target's timestamp, that target is
    unscored. Results from two checkpoints of the same event are not treated
    as two training examples.
    """
    if minimum_training_races < 4:
        raise ValueError("at least four earlier independent races required")
    if not cases:
        raise ValueError("no source-backed frozen evaluation cases supplied")
    seen: set[tuple[int, str]] = set()
    for case in cases:
        key = (case.season, case.race_id)
        if key in seen:
            raise ValueError("one prespecified checkpoint per race; duplicate event")
        seen.add(key)
        _validate_case(case)
    ordered = sorted(cases, key=lambda c: (c.observed_at, c.season, c.race_id))
    folds: list[ForwardFold] = []
    for target in ordered:
        cutoff = target.observed_at.astimezone(UTC)
        training = [
            earlier for earlier in ordered
            if (earlier.season, earlier.race_id) != (target.season, target.race_id)
            and earlier.result_published_at.astimezone(UTC) < cutoff
        ]
        if len(training) < minimum_training_races:
            continue
        selected = _choose_weight(training)
        running_leader = min(
            target.scenario.drivers, key=lambda d: d.current_position
        ).driver_number
        running = {
            car: 1.0 if car == running_leader else 0.0
            for car in target.initial_prior
        }
        candidate = {
            "pre-race": dict(target.initial_prior),
            "running-order": running,
            "green-continuation": _probabilities(target, 1.0),
            "walkforward-fusion": _probabilities(target, selected),
        }
        checks = {
            label: _proper_score(distribution, target.winner_driver_number)
            for label, distribution in candidate.items()
        }
        folds.append(ForwardFold(
            season=target.season, race_id=target.race_id, lap=target.lap,
            as_of=cutoff.isoformat(),
            last_training_result_at=max(
                c.result_published_at.astimezone(UTC) for c in training
            ).isoformat(),
            training_races=len(training),
            selected_scenario_weight=selected,
            target_winner=target.winner_driver_number,
            winner_choices={
                label: max(dist, key=lambda car: (dist[car], -car))
                for label, dist in candidate.items()
            },
            multiclass_brier={label: score[0] for label, score in checks.items()},
            winner_log_loss={label: score[1] for label, score in checks.items()},
        ))
    if not folds:
        raise ValueError("insufficient independent prior completed races for evaluation")
    payload = {
        "revision": EVALUATION_REVISION,
        "researchOnly": True,
        "modelPromotionAllowed": False,
        "minimumTrainingRaces": minimum_training_races,
        "candidateWeights": WEIGHT_GRID,
        "eligibleRaces": len(ordered),
        "scoredRaces": len(folds),
        "unscoredRaces": len(ordered) - len(folds),
        "folds": [asdict(fold) for fold in folds],
        "pairedSummary": _summarize(folds),
        "caveats": (
            "Only one prespecified checkpoint per race; no within-race leakage.",
            "Select weight using earlier publicly available results, never target results.",
            "Proper scores are diagnostics, not evidence of deployment qualification.",
            "Source, licensing, entry roster, priors, and result provenance must be audited.",
            "No trained pit/retirement model or prospective calibration is claimed.",
        ),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ForwardReport(
        revision=EVALUATION_REVISION, research_only=True,
        model_promotion_allowed=False, minimum_training_races=minimum_training_races,
        candidate_weights=WEIGHT_GRID, eligible_races=len(ordered),
        scored_races=len(folds), unscored_races=len(ordered)-len(folds),
        folds=tuple(folds), paired_summary=payload["pairedSummary"],
        caveats=payload["caveats"], report_sha256=digest,
    )


def report_to_wire(report: ForwardReport) -> dict[str, object]:
    """Exact artifact shape; digest covers all stored fields except itself."""
    return {
        "revision": report.revision,
        "researchOnly": report.research_only,
        "modelPromotionAllowed": report.model_promotion_allowed,
        "minimumTrainingRaces": report.minimum_training_races,
        "candidateWeights": list(report.candidate_weights),
        "eligibleRaces": report.eligible_races,
        "scoredRaces": report.scored_races,
        "unscoredRaces": report.unscored_races,
        "folds": [asdict(fold) for fold in report.folds],
        "pairedSummary": report.paired_summary,
        "caveats": list(report.caveats),
        "reportSha256": report.report_sha256,
    }


def read_forward_report(path: Path) -> dict[str, object]:
    """Refuse modified reports and any document claiming promotion."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("unable to read research report") from error
    required = {
        "revision", "researchOnly", "modelPromotionAllowed",
        "minimumTrainingRaces", "candidateWeights", "eligibleRaces",
        "scoredRaces", "unscoredRaces", "folds", "pairedSummary", "caveats",
        "reportSha256",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise ValueError("research report schema invalid")
    if (
        document["revision"] != EVALUATION_REVISION
        or document["researchOnly"] is not True
        or document["modelPromotionAllowed"] is not False
        or document["candidateWeights"] != list(WEIGHT_GRID)
        or not isinstance(document["reportSha256"], str)
    ):
        raise ValueError("research report status or revision invalid")
    given = document["reportSha256"]
    expected = hashlib.sha256(
        json.dumps(
            {key: val for key, val in document.items() if key != "reportSha256"},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    if given != expected:
        raise ValueError("research report digest mismatch")
    return document


def write_forward_report(path: Path, report: ForwardReport) -> Path:
    """Immutable output file; never rewrite scored results in place."""
    document = report_to_wire(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + "\n")
    except FileExistsError:
        if read_forward_report(path) != document:
            raise ValueError("existing research report differs; refusing overwrite") from None
    return path
