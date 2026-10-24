"""Pre-race prediction API: honest modes, supported checkpoints, validation, quality."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from f1engine.app import ApiSettings, LedgerStore, create_app
from f1engine.data_quality import profile
from f1engine.evidence import PredictionRecord
from f1engine.ingestion import PinnedDataset
from f1engine.prediction_api import build_envelope, evaluate_winners


def _client(dataset: PinnedDataset, ledger: Path) -> TestClient:
    return TestClient(create_app(ApiSettings(ledger_path=ledger), dataset=dataset))


def _records(ledger: Path) -> list[PredictionRecord]:
    return [r for r in LedgerStore(ledger).read_all() if isinstance(r, PredictionRecord)]


@pytest.fixture()
def client(predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]) -> TestClient:
    return _client(predictable_dataset, ledger_factory(4, 5))


def test_catalog_marks_only_rounds_with_records_as_supported(client: TestClient) -> None:
    body = client.get("/api/prediction-catalog").json()
    by_round = {race["round"]: race for race in body["races"]}
    assert body["supportedTotal"] == 2
    for number in (4, 5):
        assert by_round[number]["predictionMode"] == "historical-backtest"
        pre = by_round[number]["checkpoints"][0]
        assert pre == {"checkpoint": "pre-weekend", "supported": True, "reason": None}
    for number in (1, 2, 3):
        assert by_round[number]["predictionMode"] == "unavailable"
        assert by_round[number]["checkpoints"][0]["supported"] is False
        assert "ledger" in by_round[number]["checkpoints"][0]["reason"]
    # Post-qualifying is never claimed: the models never read the round's own qualifying.
    assert all(not race["checkpoints"][1]["supported"] for race in body["races"])
    assert body["upcomingRaces"] == 0 and "No upcoming races" in body["upcomingNote"]
    assert body["advisoryOnly"] is True


def test_prediction_envelope_is_labeled_historical_and_separates_timestamps(
    client: TestClient,
) -> None:
    before = datetime.now(UTC)
    response = client.get("/api/races/fifth-grand-prix/prediction", params={"season": 2021})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["predictionMode"] == "historical-backtest"
    assert body["checkpoint"] == "pre-weekend"
    assert body["freshness"] == "historical"
    # No invented forecast time; the evidence id time is the snapshot's, not the request's.
    assert body["predictionGeneratedAt"] is None
    fetched = datetime.fromisoformat(body["fetchedAt"])
    assert fetched >= before - timedelta(seconds=1)
    assert body["evidenceGeneratedAt"] != body["fetchedAt"]
    cutoff = body["featureCutoff"]
    assert (cutoff["throughSeason"], cutoff["throughRound"]) == (2021, 4)
    probabilities = [d["winProbability"] for d in body["drivers"]]
    assert math.isclose(sum(probabilities), 1.0, abs_tol=1e-6)
    assert probabilities == sorted(probabilities, reverse=True)
    assert [d["rank"] for d in body["drivers"]] == list(range(1, len(probabilities) + 1))
    assert all("podiumProbability" not in d for d in body["drivers"])
    outputs = {o["output"]: o["supported"] for o in body["outputs"]}
    assert outputs["winner"] is True
    assert not any(outputs[name] for name in ("points", "finishPosition", "dnfRisk", "intervals"))
    assert math.isclose(body["baseline"]["winProbability"], 1 / len(probabilities))
    missing = {m["input"] for m in body["missingInputs"]}
    assert {"Weather forecast", "Qualifying and grid for this race"} <= missing
    assert body["advisoryOnly"] is True


def test_podium_is_withheld_when_values_do_not_add_up_to_three(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path],
) -> None:
    record = _records(ledger_factory(5))[0]
    race = next(r for r in predictable_dataset.races if r.round == 5)
    incoherent = record.model_copy(update={"ensemble": record.ensemble.model_copy(
        update={"podium": dict.fromkeys(record.ensemble.podium, 0.5)})})
    envelope = build_envelope(predictable_dataset, [incoherent], race, "pre-weekend")
    podium = next(o for o in envelope.outputs if o.output == "podium")
    assert podium.supported is False and "three" in podium.reason
    check = next(c for c in envelope.validation if "podium" in c.check)
    assert check.passed is False


@pytest.mark.parametrize(
    ("params", "status", "code"),
    [
        ({"season": 2021, "checkpoint": "post-qualifying"}, 409, "CHECKPOINT_UNSUPPORTED"),
        ({"season": 2021, "checkpoint": "live"}, 422, None),
        ({}, 422, None),
        ({"season": 2021, "checkpoint": "pre-weekend"}, 404, "PREDICTION_UNAVAILABLE"),
    ],
)
def test_invalid_or_unsupported_requests_are_refused(
    client: TestClient, params: dict[str, object], status: int, code: str | None,
) -> None:
    race = "fifth-grand-prix" if params.get("checkpoint") != "pre-weekend" else "second-grand-prix"
    response = client.get(f"/api/races/{race}/prediction", params=params)
    assert response.status_code == status
    if code:
        assert response.json()["detail"]["code"] == code


def test_unknown_race_is_404(client: TestClient) -> None:
    response = client.get("/api/races/not-a-race/prediction", params={"season": 2021})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "RACE_UNKNOWN"


def test_tampered_ledger_fails_closed_without_leaking_paths(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path], tmp_path: Path,
) -> None:
    ledger = ledger_factory(4, 5)
    lines = ledger.read_text().splitlines()
    first = json.loads(lines[0])
    winners = first["ensemble"]["winner"]
    a, b = list(winners)[:2]
    winners[a], winners[b] = winners[b], winners[a]
    lines[0] = json.dumps(first, separators=(",", ":"), sort_keys=True)
    ledger.write_text("\n".join(lines) + "\n")
    client = _client(predictable_dataset, ledger)
    for path in ("/api/races/fifth-grand-prix/prediction?season=2021", "/api/prediction-catalog"):
        response = client.get(path)
        assert response.status_code == 503
        assert str(tmp_path) not in response.text
    ready = client.get("/readyz")
    assert ready.status_code == 503
    assert ready.json()["detail"]["code"] == "NOT_READY"


def test_readiness_reports_loaded_dataset(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "datasetId": response.json()["datasetId"]}


def test_evaluation_scores_against_winners_and_reports_uncertainty(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path],
) -> None:
    view = evaluate_winners(predictable_dataset, _records(ledger_factory(4, 5)), resamples=200)
    assert view.rounds == 2
    names = [score.model_id for score in view.scores]
    assert names == ["m1-gbm", "m2-logit", "m3-form", "ensemble"]
    for score in [*view.scores, view.baseline]:
        for metric in (score.winner_hit_rate, score.winner_log_loss, score.winner_brier):
            assert metric.ci_low <= metric.value <= metric.ci_high
    # A blind guess earns its expected 1-in-N hit rate, not zero from a tie-break.
    field = len(_records(ledger_factory(4, 5))[0].ensemble.winner)
    assert math.isclose(view.baseline.winner_hit_rate.value, 1 / field)
    assert "Not established" in view.calibration_verdict


def test_data_quality_flags_invalid_probabilities_as_blocking(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path],
) -> None:
    record = _records(ledger_factory(5))[0]
    broken_winner = dict.fromkeys(record.ensemble.winner, 0.01)
    broken = record.model_copy(update={"ensemble": record.ensemble.model_copy(
        update={"winner": broken_winner})})
    report = profile(predictable_dataset, [broken])
    finding = next(f for f in report.findings if f.check.startswith("winner probabilities"))
    assert finding.passed is False and finding.blocks_inference is True
    assert report.inference_blocked is True


def test_data_quality_warns_when_source_is_stale(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path],
) -> None:
    updated = datetime.fromisoformat(predictable_dataset.provenance.generatedAt)
    report = profile(predictable_dataset, _records(ledger_factory(5)),
                     now=updated + timedelta(days=90))
    stale = next(f for f in report.findings if f.check == "source freshness")
    assert stale.passed is False and stale.severity == "warning"
    assert stale.blocks_inference is False
    assert report.source_age_days == 90


def test_data_quality_endpoint_profiles_coverage(client: TestClient) -> None:
    body = client.get("/api/data-quality").json()
    assert body["inferenceBlocked"] is False
    assert body["coverage"][0]["predictionRecords"] == 2
    assert {f["check"] for f in body["findings"]} >= {
        "referential integrity", "no training on the target round or later",
    }


# ---- review follow-ups: edge cases the first pass did not cover ----------

def test_leakage_finding_is_clean_for_walk_forward_records_and_blocks_otherwise(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path],
) -> None:
    record = _records(ledger_factory(5))[0]
    clean = profile(predictable_dataset, [record])
    check = next(f for f in clean.findings if f.check.startswith("no training on the target"))
    assert check.passed is True
    model_id, prediction = next(iter(record.models.items()))
    leaked_diag = prediction.diagnostics.model_copy(update={"trained_through_round": 6})
    leaked = record.model_copy(update={"models": record.models | {
        model_id: prediction.model_copy(update={"diagnostics": leaked_diag})}})
    report = profile(predictable_dataset, [leaked])
    finding = next(f for f in report.findings if f.check.startswith("no training on the target"))
    assert finding.passed is False and finding.blocks_inference is True


def _with_winner(record: PredictionRecord, winner: dict[str, float]) -> PredictionRecord:
    ensemble = record.ensemble.model_copy(update={"winner": winner})
    return record.model_copy(update={"ensemble": ensemble})


def test_calibration_bins_cover_every_prediction_once_including_edges(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path],
) -> None:
    four, five = _records(ledger_factory(4, 5))
    drivers = list(five.ensemble.winner)
    edge = dict.fromkeys(drivers, 0.0)
    edge[drivers[0]], edge[drivers[1]], edge[drivers[2]] = 0.4, 0.05, 0.55
    certain = dict.fromkeys(list(four.ensemble.winner), 0.0)
    certain[next(iter(certain))] = 1.0
    view = evaluate_winners(
        predictable_dataset, [_with_winner(four, certain), _with_winner(five, edge)], resamples=50,
    )
    total = len(certain) + len(edge)
    assert sum(b.predictions for b in view.calibration) == total
    by_lower = {b.lower: b for b in view.calibration}
    assert by_lower[0.05].predictions >= 1  # p = 0.05 opens the second bin
    assert by_lower[0.4].predictions >= 3  # 0.4, 0.55 and the certain 1.0


def test_tied_favorites_share_the_hit(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path],
) -> None:
    record = _records(ledger_factory(5))[0]
    field = list(record.ensemble.winner)
    uniform = _with_winner(record, dict.fromkeys(field, 1 / len(field)))
    view = evaluate_winners(predictable_dataset, [uniform], resamples=20)
    ensemble = next(score for score in view.scores if score.model_id == "ensemble")
    assert math.isclose(ensemble.winner_hit_rate.value, 1 / len(field))


def test_catalog_keys_by_season_for_repeated_race_ids(real_snapshot: PinnedDataset) -> None:
    from f1engine.prediction_api import build_catalog

    catalog = build_catalog(real_snapshot, [])
    keys = [(race.season, race.race_id) for race in catalog.races]
    assert len(keys) == len(set(keys)) == len(real_snapshot.races)
    assert len({race.race_id for race in catalog.races}) < len(keys)  # ids do repeat
    assert catalog.supported_total == 0


def test_rounds_without_results_are_upcoming_and_never_predicted(
    predictable_dataset: PinnedDataset,
) -> None:
    from dataclasses import replace

    from f1engine.prediction_api import build_catalog

    future = replace(predictable_dataset, results=tuple(
        row for row in predictable_dataset.results if row.round != 5))
    catalog = build_catalog(future, [])
    race = next(r for r in catalog.races if r.round == 5)
    assert race.status == "upcoming" and race.prediction_mode == "unavailable"
    assert "entry list" in (race.checkpoints[0].reason or "")
    assert catalog.upcoming_races == 1


def test_first_race_has_no_earlier_cutoff(predictable_dataset: PinnedDataset) -> None:
    from f1engine.prediction_api import _feature_cutoff

    first = min(predictable_dataset.races, key=lambda r: (r.season, r.round))
    cutoff = _feature_cutoff(predictable_dataset, first)
    assert cutoff.through_round is None and cutoff.through_race_date is None


def test_reasons_mark_joint_ranks(predictable_dataset: PinnedDataset) -> None:
    from f1engine.features import build_asof_features
    from f1engine.prediction_api import _reasons

    rows = [r for r in build_asof_features(predictable_dataset).rows if r.round == 5]
    tied = [r.model_copy(update={
        "team_points_mean": 10.0, "form_finish_mean": None, "q_delta_pole_ms": None,
        "track_finish_mean": None, "starts": 20,
    }) for r in rows]
    notes = _reasons(tied[0], tied)
    assert any("Ranks joint 1" in note and "team points" in note for note in notes)


def test_coverage_lag_is_flagged_without_blocking(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path],
) -> None:
    latest = max(r.date for r in predictable_dataset.races)
    report = profile(predictable_dataset, _records(ledger_factory(5)),
                     now=datetime.fromisoformat(latest).replace(tzinfo=UTC) + timedelta(days=400))
    lag = next(f for f in report.findings if f.check == "data coverage is current")
    assert lag.passed is False and lag.blocks_inference is False
    assert report.data_through_date == latest and report.coverage_lag_days == 400
