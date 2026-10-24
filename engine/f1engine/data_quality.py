"""Data-quality profile of the pinned snapshot and the prediction ledger.

Each finding says how severe it is, which records or features it touches, and
whether it blocks training or inference. Blocking follows the model input
contract: a broken key, a dangling reference or an invalid winner
distribution blocks; sparse optional features only warn, because the models
treat a missing feature value as missing (NaN), never as an imputed number.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from f1engine.evidence import PredictionRecord
from f1engine.ingestion import PinnedDataset
from f1engine.wire import WireModel

Severity = Literal["info", "warning", "error"]

# Plausible ranges: anything outside is a data error, not an outlier.
_LAP_MS_RANGE = (40_000, 200_000)
_MAX_POSITION = 30
_STALE_AFTER_DAYS = 30
_COVERAGE_LAG_DAYS = 60


class QualityFinding(WireModel):
    check: str
    severity: Severity
    passed: bool
    affected: int
    detail: str
    examples: list[str]
    blocks_training: bool
    blocks_inference: bool


class SeasonCoverage(WireModel):
    season: int
    races: int
    rounds_with_results: int
    rounds_with_qualifying: int
    prediction_records: int


class DataQualityReport(WireModel):
    dataset_id: str
    dataset_digest: str
    source_updated_at: str
    checked_at: str
    source_age_days: int
    data_through_date: str
    coverage_lag_days: int
    coverage: list[SeasonCoverage]
    findings: list[QualityFinding]
    training_blocked: bool
    inference_blocked: bool
    summary: str


def _finding(
    check: str,
    problems: Sequence[str],
    *,
    severity: Severity,
    detail: str,
    blocks_training: bool = False,
    blocks_inference: bool = False,
) -> QualityFinding:
    failed = bool(problems)
    return QualityFinding(
        check=check,
        severity=severity if failed else "info",
        passed=not failed,
        affected=len(problems),
        detail=detail,
        examples=list(problems[:5]),
        blocks_training=failed and blocks_training,
        blocks_inference=failed and blocks_inference,
    )


def _duplicates(keys: Sequence[tuple[object, ...]]) -> list[str]:
    return [str(key) for key, count in Counter(keys).items() if count > 1]


def profile(
    dataset: PinnedDataset,
    records: Sequence[PredictionRecord],
    *,
    now: datetime | None = None,
) -> DataQualityReport:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    findings: list[QualityFinding] = []
    race_keys = {(r.season, r.round) for r in dataset.races}
    driver_ids = {d.driver_id for d in dataset.drivers}
    team_ids = {c.constructor_id for c in dataset.constructors}

    findings.append(
        _finding(
            "unique race keys (season, round)",
            _duplicates([(r.season, r.round) for r in dataset.races]),
            severity="error",
            detail="Each round must appear once in the races table.",
            blocks_training=True,
            blocks_inference=True,
        )
    )
    findings.append(
        _finding(
            "unique result keys (season, round, driver)",
            _duplicates([(r.season, r.round, r.driver_id) for r in dataset.results]),
            severity="error",
            detail="A driver may have one result per round.",
            blocks_training=True,
            blocks_inference=True,
        )
    )
    findings.append(
        _finding(
            "unique qualifying keys (season, round, driver)",
            _duplicates([(q.season, q.round, q.driver_id) for q in dataset.qualifying]),
            severity="error",
            detail="A driver may have one qualifying entry per round.",
            blocks_training=True,
        )
    )
    dangling = [
        f"result {r.season}-{r.round} {r.driver_id}"
        for r in dataset.results
        if (r.season, r.round) not in race_keys
        or r.driver_id not in driver_ids
        or r.constructor_id not in team_ids
    ] + [
        f"qualifying {q.season}-{q.round} {q.driver_id}"
        for q in dataset.qualifying
        if (q.season, q.round) not in race_keys
        or q.driver_id not in driver_ids
        or q.constructor_id not in team_ids
    ]
    findings.append(
        _finding(
            "referential integrity",
            dangling,
            severity="error",
            detail="Every result and qualifying row must point at a known race, driver and team.",
            blocks_training=True,
            blocks_inference=True,
        )
    )
    winners = Counter((r.season, r.round) for r in dataset.results if r.position == 1)
    rounds_with_results = {(r.season, r.round) for r in dataset.results}
    bad_winners = [
        f"{s}-{n}: {winners.get((s, n), 0)} winners"
        for s, n in sorted(rounds_with_results)
        if winners.get((s, n), 0) != 1
    ]
    findings.append(
        _finding(
            "exactly one winner per completed round",
            bad_winners,
            severity="error",
            detail="Evaluation labels need one classified winner per race.",
            blocks_training=True,
        )
    )
    bad_positions = [
        f"{r.season}-{r.round} {r.driver_id}: P{r.position}"
        for r in dataset.results
        if r.position is not None and not 1 <= r.position <= _MAX_POSITION
    ]
    findings.append(
        _finding(
            "plausible finishing positions",
            bad_positions,
            severity="error",
            detail=f"Positions must be between 1 and {_MAX_POSITION}.",
            blocks_training=True,
        )
    )
    lo, hi = _LAP_MS_RANGE
    bad_laps = [
        f"{q.season}-{q.round} {q.driver_id}: {value} ms"
        for q in dataset.qualifying
        for value in (q.q1_ms, q.q2_ms, q.q3_ms)
        if value is not None and not lo <= value <= hi
    ]
    findings.append(
        _finding(
            "plausible qualifying lap times",
            bad_laps,
            severity="warning",
            detail=f"Lap times outside {lo // 1000}-{hi // 1000} s are treated as suspect.",
        )
    )
    no_lap = [
        f"{q.season}-{q.round} {q.driver_id}"
        for q in dataset.qualifying
        if q.q1_ms is None and q.q2_ms is None and q.q3_ms is None
    ]
    findings.append(
        QualityFinding(
            check="qualifying entries with no lap time",
            severity="info" if len(no_lap) <= 0.05 * max(len(dataset.qualifying), 1) else "warning",
            passed=True,
            affected=len(no_lap),
            detail=(
                f"{len(no_lap)} of {len(dataset.qualifying)} entries have no time; the qualifying "
                "features are left missing for those drivers, never filled in."
            ),
            examples=no_lap[:5],
            blocks_training=False,
            blocks_inference=False,
        )
    )
    rounds_with_qualifying = {(q.season, q.round) for q in dataset.qualifying}
    missing_q = [f"{s}-{n}" for s, n in sorted(rounds_with_results - rounds_with_qualifying)]
    findings.append(
        _finding(
            "qualifying coverage of completed rounds",
            missing_q,
            severity="warning",
            detail=(
                "Rounds without qualifying leave qualifying-gap features missing for later rounds."
            ),
        )
    )

    bad_records: list[str] = []
    for record in records:
        label = f"{record.race.season}-{record.race.round}"
        for name, values in [("ensemble", record.ensemble.winner)] + [
            (model_id, prediction.winner) for model_id, prediction in record.models.items()
        ]:
            total = sum(values.values())
            if not math.isclose(total, 1.0, abs_tol=1e-6) or any(
                not (0.0 <= p <= 1.0) or not math.isfinite(p) for p in values.values()
            ):
                bad_records.append(f"{label} {name}: sum {total:.6f}")
    findings.append(
        _finding(
            "winner probabilities form a valid distribution",
            bad_records,
            severity="error",
            detail="Every stored winner distribution must lie in [0, 1] and sum to 1.",
            blocks_inference=True,
        )
    )
    podium_sums = [sum(r.ensemble.podium.values()) for r in records]
    incoherent = [
        f"{r.race.season}-{r.race.round}: {s:.2f}"
        for r, s in zip(records, podium_sums, strict=True)
        if abs(s - 3.0) > 0.15
    ]
    findings.append(
        QualityFinding(
            check="podium probabilities sum to about 3",
            severity="warning" if incoherent else "info",
            passed=not incoherent,
            affected=len(incoherent),
            detail=(
                "Stored podium values are independent per driver; the podium output is withheld "
                "until a coherent podium model is evaluated."
            ),
            examples=incoherent[:5],
            blocks_training=False,
            blocks_inference=False,
        )
    )
    leaks = [
        f"{r.race.season}-{r.race.round} {m}: trained through "
        f"{p.diagnostics.trained_through_season}-{p.diagnostics.trained_through_round}"
        for r in records
        for m, p in r.models.items()
        if (p.diagnostics.trained_through_season, p.diagnostics.trained_through_round)
        > (r.race.season, r.race.round)
    ]
    findings.append(
        _finding(
            "no training on the target round or later",
            leaks,
            severity="error",
            detail="A stored prediction must come from a model trained only on earlier rounds.",
            blocks_inference=True,
        )
    )

    updated = datetime.fromisoformat(dataset.provenance.generatedAt.replace("Z", "+00:00"))
    age_days = max(0, (now - updated.astimezone(UTC)).days)
    stale = [f"retrieved {age_days} days ago"] if age_days > _STALE_AFTER_DAYS else []
    findings.append(
        _finding(
            "source freshness",
            stale,
            severity="warning",
            detail=(
                f"Data was retrieved {dataset.provenance.generatedAt[:10]}. Historical backtests "
                "are unaffected; current-season predictions would need a refresh."
            ),
        )
    )

    through = max((r.date for r in dataset.races), default=None)
    lag_days = max(0, (now.date() - datetime.fromisoformat(through).date()).days) if through else 0
    lagging = (
        [f"latest race {through}, {lag_days} days ago"] if lag_days > _COVERAGE_LAG_DAYS else []
    )
    findings.append(
        _finding(
            "data coverage is current",
            lagging,
            severity="warning",
            detail=(
                f"The newest race in the data is {through}. Historical backtests are "
                "unaffected; predictions for current or upcoming races are unavailable "
                "until a reviewed refresh adds them."
            ),
        )
    )

    record_counts = Counter(r.race.season for r in records)
    coverage = []
    for season in sorted({r.season for r in dataset.races}):
        coverage.append(
            SeasonCoverage(
                season=season,
                races=sum(1 for r in dataset.races if r.season == season),
                rounds_with_results=sum(1 for s, _ in rounds_with_results if s == season),
                rounds_with_qualifying=sum(1 for s, _ in rounds_with_qualifying if s == season),
                prediction_records=record_counts.get(season, 0),
            )
        )
    training_blocked = any(f.blocks_training for f in findings)
    inference_blocked = any(f.blocks_inference for f in findings)
    failed = [f for f in findings if not f.passed]
    return DataQualityReport(
        dataset_id=dataset.dataset_id,
        dataset_digest=dataset.dataset_sha256,
        source_updated_at=dataset.provenance.generatedAt,
        checked_at=now.isoformat(),
        source_age_days=age_days,
        data_through_date=through or "",
        coverage_lag_days=lag_days,
        coverage=coverage,
        findings=findings,
        training_blocked=training_blocked,
        inference_blocked=inference_blocked,
        summary=(
            "No blocking problems."
            if not (training_blocked or inference_blocked)
            else "Blocking problems found; see findings marked as blocking."
        )
        + (f" {len(failed)} check(s) need attention." if failed else ""),
    )
