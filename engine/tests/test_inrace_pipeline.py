"""Source-to-artifact replay, cutoff discipline and pre-race fusion tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from f1engine.inrace_pipeline import (
    ArtifactTampered,
    build_run_artifact,
    project_and_record,
    read_run_artifact,
)
from f1engine.lap_trace import (
    DriverOnTrack,
    LapCheckpoint,
    LapTraceRecord,
    LapTraceError,
    append_lap_checkpoint,
)
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
