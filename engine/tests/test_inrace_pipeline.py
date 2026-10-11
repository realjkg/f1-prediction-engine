"""Source-to-artifact replay, cutoff discipline and pre-race fusion tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from f1engine.app import ApiSettings, create_app
from f1engine.inrace_evaluation import FrozenEvaluationCase, evaluate_frozen_cases
from f1engine.inrace_pipeline import (
    ArtifactTampered,
    build_run_artifact,
    project_and_record,
    read_fusion_artifacts,
    read_run_artifact,
    write_fusion_artifacts,
)
from f1engine.lap_trace import LapTraceError
from f1engine.live_prior import PreRacePrior, PriorEvidenceError, combine_prerace_and_lap
from f1engine.openf1_projection import project_lap_checkpoint
from f1engine.race_simulator import ScenarioUnavailable, simulate_green_pace

START = datetime(2026, 10, 11, 13, 0, tzinfo=UTC)
CUTOFF = START + timedelta(seconds=600)


def source_bundle(later_position: bool = False) -> bytes:
    session = 55001
    events: dict[str, list[dict]] = {
        "position": [],
        "intervals": [],
        "laps": [],
        "race_control": [{
            "session_key": session, "date": (CUTOFF-timedelta(seconds=10)).isoformat(),
            "flag": "GREEN", "scope": "Track", "category": "Flag",
        }],
        "weather": [{
            "session_key": session, "date": (CUTOFF-timedelta(seconds=12)).isoformat(),
            "rainfall": 0,
        }],
        "pit": [],
    }
    for car, position, gap in ((1, 1, 0), (16, 2, 4.2)):
        events["position"].append({
            "session_key": session, "driver_number": car, "position": position,
            "date": (CUTOFF-timedelta(seconds=9)).isoformat(),
        })
        events["intervals"].append({
            "session_key": session, "driver_number": car, "gap_to_leader": gap,
            "date": (CUTOFF-timedelta(seconds=9)).isoformat(),
        })
        for number in range(1, 5):
            events["laps"].append({
                "session_key": session, "driver_number": car, "lap_number": number,
                "lap_duration": 100.0 + (car / 100) + number * 0.04,
                "date_start": (START + timedelta(seconds=(number-1) * 100)).isoformat(),
            })
    if later_position:
        events["position"].append({
            "session_key": session, "driver_number": 16, "position": 1,
            "date": (CUTOFF+timedelta(seconds=15)).isoformat(),
        })
    return json.dumps({"session_key": session, "events": events}).encode()


def replay(path: Path, raw: bytes | None = None):
    return project_and_record(
        raw if raw is not None else source_bundle(),
        trace_path=path / "trace.jsonl", artifact_root=path / "artifacts",
        season=2026, race_id="singapore", session_key=55001, lap=5,
        total_laps=62, cutoff=CUTOFF, captured_at=CUTOFF+timedelta(seconds=2),
        entrant_numbers=(1, 16), source_type="synthetic-fixture",
        rights_evidence=None, trials=500,
    )


def test_asof_projection_ignores_future_position_and_labels(tmp_path: Path):
    c = project_lap_checkpoint(
        source_bundle(later_position=True), season=2026,
        race_id="singapore", session_key=55001, lap=5, total_laps=62,
        cutoff=CUTOFF, captured_at=CUTOFF+timedelta(seconds=2),
        entrant_numbers=(1, 16), source_type="synthetic-fixture",
        rights_evidence=None,
    )
    assert c.lap == 5 and c.total_laps == 62
    assert [(d.driver_number, d.position) for d in c.running_order] == [(1, 1), (16, 2)]
    assert c.track_status == "GREEN"
    assert c.track_condition == "dry"
    assert all(len(d.recent_lap_seconds) == 3 for d in c.running_order)


def test_artifact_loop_is_idempotent_and_scenario_is_bound(tmp_path: Path):
    record, a = replay(tmp_path)
    _, same = replay(tmp_path)
    assert a == same
    assert a.status == "scenario" and a.scenario is not None
    assert a.model_ready is False
    assert a.scenario.status == "experimental-scenario-only"
    assert a.scenario.checkpoint_record_sha256 == record.record_sha256
    stored = read_run_artifact(tmp_path/"artifacts", season=2026,
                               race_id="singapore", lap=5,
                               checkpoint_sha256=record.record_sha256)
    assert stored == a
    artifact_path = tmp_path/"artifacts"/"2026-singapore"/"lap-005"/(
        record.record_sha256+".json")
    raw = json.loads(artifact_path.read_text())
    raw["status"] = "insufficient-evidence"
    artifact_path.write_text(json.dumps(raw))
    with pytest.raises((ArtifactTampered, LapTraceError)):
        read_run_artifact(tmp_path/"artifacts", season=2026,
                          race_id="singapore", lap=5,
                          checkpoint_sha256=record.record_sha256)


def prior() -> PreRacePrior:
    return PreRacePrior(
        season=2026, race_id="singapore", session_key=55001,
        model_revision="fixed-prospective-challenger-v1",
        model_artifact_sha256="b"*64, dataset_sha256="c"*64,
        source_issued_at=START-timedelta(days=1),
        frozen_at=START-timedelta(hours=1),
        race_start_at=START-timedelta(minutes=10),
        driver_win_probabilities={1: .7, 16: .3},
    )


def test_prior_fusion_bound_to_season_session_checkpoint(tmp_path: Path):
    record, artifact = replay(tmp_path)
    assert artifact.scenario is not None
    fusion = combine_prerace_and_lap(prior(), record, artifact.scenario,
                                     green_scenario_weight=.35)
    assert fusion.status == "unqualified-blend"
    assert fusion.promoted is False
    assert fusion.checkpoint_sha256 == record.record_sha256
    assert sum(x.blended_research_weight for x in fusion.candidates) == pytest.approx(1)
    assert len(fusion.output_sha256) == 64
    again = combine_prerace_and_lap(prior(), record, artifact.scenario,
                                    green_scenario_weight=.35)
    assert fusion == again
    with pytest.raises(PriorEvidenceError, match="race/session"):
        combine_prerace_and_lap(prior().model_copy(update={"season": 2025}),
                                record, artifact.scenario, green_scenario_weight=.35)
    with pytest.raises(PriorEvidenceError, match="entrant"):
        combine_prerace_and_lap(prior().model_copy(update={
            "driver_win_probabilities": {1: .5, 44: .5}
        }), record, artifact.scenario, green_scenario_weight=.35)
    with pytest.raises(PriorEvidenceError, match="weight"):
        combine_prerace_and_lap(prior(), record, artifact.scenario,
                                green_scenario_weight=1.5)


def test_frozen_pre_race_prior_rejects_hindsight():
    item = prior().model_dump()
    item["frozen_at"] = START + timedelta(hours=1)
    with pytest.raises(ValidationError, match="precede race start"):
        PreRacePrior.model_validate(item)


def test_scenario_refuses_missing_gaps_and_unsafe_race_status(tmp_path: Path):
    record, artifact = replay(tmp_path)
    checkpoint = record.checkpoint
    missing = checkpoint.model_copy(update={
        "running_order": (checkpoint.running_order[0],
                         checkpoint.running_order[1].model_copy(update={
                             "gap_to_leader_seconds": None,
                         })),
    })
    bad_record = record.model_copy(update={"checkpoint": missing})
    with pytest.raises(ScenarioUnavailable, match="numeric gaps"):
        simulate_green_pace(bad_record)
    unsafe_record = record.model_copy(update={
        "checkpoint": checkpoint.model_copy(update={"track_status": "SC"}),
    })
    result = build_run_artifact(unsafe_record)
    assert result.status == "insufficient-evidence"
    assert result.scenario is None and result.refusal_reason


def test_cutoff_rejects_future_or_incomplete_source(tmp_path: Path):
    raw = json.loads(source_bundle())
    raw["events"]["position"] = raw["events"]["position"][:1]
    with pytest.raises(LapTraceError, match="position feed"):
        replay(tmp_path, json.dumps(raw).encode())
    with pytest.raises(LapTraceError, match="future"):
        project_lap_checkpoint(
            source_bundle(), season=2026, race_id="singapore",
            session_key=55001, lap=5, total_laps=62,
            cutoff=CUTOFF, captured_at=CUTOFF-timedelta(seconds=2),
            entrant_numbers=(1, 16), source_type="synthetic-fixture",
            rights_evidence=None,
        )


def test_api_joins_only_verifiable_prior_and_lap_artifacts(
    predictable_dataset, tmp_path: Path,
) -> None:
    record, artifact = replay(tmp_path)
    settings = ApiSettings(
        lap_trace_path=tmp_path / "trace.jsonl",
        inrace_artifact_dir=tmp_path / "artifacts",
    )
    client = TestClient(create_app(settings, dataset=predictable_dataset))
    scenario = client.get("/api/races/singapore/lap-scenario?season=2026&lap=5")
    assert scenario.status_code == 200
    assert scenario.json()["checkpointSha256"] == record.record_sha256
    assert scenario.json()["modelReady"] is False
    assert scenario.json()["sourceType"] == "synthetic-fixture"
    missing = client.get("/api/races/singapore/lap-fusion?season=2026&lap=5")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "PRIOR_FUSION_NOT_FOUND"

    saved = write_fusion_artifacts(
        tmp_path/"artifacts", record, artifact, prior(), scenario_weight=.3
    )
    assert saved == read_fusion_artifacts(tmp_path/"artifacts", record, artifact)
    result = client.get("/api/races/singapore/lap-fusion?season=2026&lap=5")
    assert result.status_code == 200
    assert result.json()["outputSha256"] == saved.output_sha256
    assert result.json()["promoted"] is False
    assert sum(x["blendedResearchWeight"] for x in result.json()["candidates"]) == pytest.approx(1)

    filename = tmp_path/"artifacts"/"2026-singapore"/"lap-005"/(
        record.record_sha256 + ".prior.json"
    )
    tampered = json.loads(filename.read_text(encoding="utf-8"))
    tampered["driverWinProbabilities"]["1"] = .85
    filename.write_text(json.dumps(tampered), encoding="utf-8")
    refused = client.get("/api/races/singapore/lap-fusion?season=2026&lap=5")
    assert refused.status_code == 503
    assert refused.json()["detail"]["code"] == "ARTIFACT_TAMPERED"


def test_paired_scoring_requires_frozen_result_after_lap(tmp_path: Path):
    record, artifact = replay(tmp_path)
    assert artifact.scenario is not None
    combined = combine_prerace_and_lap(
        prior(), record, artifact.scenario, green_scenario_weight=.4
    )
    case = FrozenEvaluationCase(
        season=2026, race_id="singapore", lap=5, observed_at=CUTOFF,
        result_published_at=CUTOFF+timedelta(hours=2),
        winner_driver_number=1,
        initial_prior=prior().driver_win_probabilities,
        scenario=artifact.scenario, combined=combined,
    )
    scores = evaluate_frozen_cases([case])
    assert set(scores) == {
        "pre-race", "running-order",
        "green-continuation", "research-combination",
    }
    assert all(score.races == 1 and score.checkpoints == 1 for score in scores.values())
    assert scores["pre-race"].winner_hit_rate == 1
    assert scores["pre-race"].mean_multiclass_brier == pytest.approx(.18)
    assert scores["research-combination"].mean_multiclass_brier >= 0
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_frozen_cases([case, case])
    with pytest.raises(ValueError, match="result timestamp"):
        evaluate_frozen_cases([case.__class__(**{
            **vars(case),
            "result_published_at": CUTOFF - timedelta(seconds=1),
        })])
