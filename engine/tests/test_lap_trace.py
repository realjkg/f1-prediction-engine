"""In-race checkpoint integrity, replay, and API fail-closed behavior."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from f1engine.app import ApiSettings, create_app
from f1engine.lap_trace import (
    DriverOnTrack, LapCheckpoint, LapTraceError, LapTraceTampered,
    append_lap_checkpoint, get_lap_observation, verify_lap_trace,
)

AT = datetime(2026, 10, 11, 12, 30, tzinfo=UTC)


def sample(lap: int = 25, delta: int = 0, live: bool = False) -> LapCheckpoint:
    now = AT + timedelta(seconds=delta)
    return LapCheckpoint(
        season=2026, race_id="singapore", session_key=123456,
        lap=lap, total_laps=62,
        observed_at=now, captured_at=now + timedelta(seconds=3),
        provider="synthetic-test-only",
        source_type="licensed-live" if live else "synthetic-fixture",
        rights_evidence="reviewed-source-record" if live else None,
        source_payload_sha256="a" * 64,
        running_order=(
            DriverOnTrack(driver_number=1, position=1, gap_to_leader_seconds=0),
            DriverOnTrack(driver_number=16, position=2, gap_to_leader_seconds=4.1),
            DriverOnTrack(driver_number=44, position=3),
        ),
        unavailable_fields=("tire_age_laps", "pit_stops", "track_condition"),
    )


def test_append_and_exact_lap_replay_is_a_trace_not_a_forecast(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    first = append_lap_checkpoint(path, sample())
    later = append_lap_checkpoint(path, sample(26, 95))
    assert first.previous_sha256 is None
    assert later.previous_sha256 == first.record_sha256
    assert len(verify_lap_trace(path)) == 2
    assert get_lap_observation(path, season=2026, race_id="singapore", lap=25) == first
    assert get_lap_observation(path, season=2026, race_id="singapore") == later
    assert get_lap_observation(path, season=2026, race_id="bahrain") is None
    assert later.forecast_status == "not-qualified"
    assert later.advisory_only
    assert "winner" not in later.model_dump_json()


def test_changing_observed_position_breaks_hash(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    append_lap_checkpoint(path, sample())
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["checkpoint"]["runningOrder"][1]["gapToLeaderSeconds"] = 0.1
    path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
    with pytest.raises(LapTraceTampered, match="hash"):
        verify_lap_trace(path)


def test_reject_nonmonotonic_or_cross_session_append(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    append_lap_checkpoint(path, sample())
    with pytest.raises(LapTraceError, match="older"):
        append_lap_checkpoint(path, sample(24, 95))
    with pytest.raises(LapTraceError, match="older"):
        append_lap_checkpoint(path, sample(26, 0))
    with pytest.raises(LapTraceError, match="different event"):
        append_lap_checkpoint(
            path, sample(26, 95).model_copy(update={"session_key": 789}),
        )


def test_invalid_positions_time_and_lap_fail_closed() -> None:
    item = sample()
    with pytest.raises(ValidationError, match="exceed"):
        LapCheckpoint.model_validate(item.model_dump() | {"lap": 63})
    with pytest.raises(ValidationError, match="duplicate"):
        LapCheckpoint.model_validate(item.model_dump() | {
            "running_order": (item.running_order[0], item.running_order[0]),
        })
    with pytest.raises(ValidationError, match="position-sorted"):
        LapCheckpoint.model_validate(item.model_dump() | {
            "running_order": tuple(reversed(item.running_order)),
        })
    with pytest.raises(ValidationError, match="available"):
        LapCheckpoint.model_validate(item.model_dump() | {
            "captured_at": item.observed_at - timedelta(seconds=1),
        })
    with pytest.raises(ValidationError):
        DriverOnTrack(driver_number=1, position=1, gap_to_leader_seconds=float("nan"))


def test_live_cannot_hide_missing_rights_or_stale_source(tmp_path: Path) -> None:
    item = sample(live=True)
    with pytest.raises(ValidationError, match="rights evidence"):
        LapCheckpoint.model_validate(item.model_dump() | {"rights_evidence": None})
    with pytest.raises(ValidationError, match="stale"):
        LapCheckpoint.model_validate(item.model_dump() | {
            "captured_at": item.observed_at + timedelta(seconds=121),
        })
    path = tmp_path / "trace.jsonl"
    append_lap_checkpoint(path, item)
    assert get_lap_observation(
        path, season=2026, race_id="singapore",
        now=item.observed_at + timedelta(seconds=60),
    ) is not None
    with pytest.raises(LapTraceError, match="stale"):
        get_lap_observation(
            path, season=2026, race_id="singapore",
            now=item.observed_at + timedelta(seconds=180),
        )
    # A historical exact-lap replay is still allowed but remains timestamped.
    assert get_lap_observation(
        path, season=2026, race_id="singapore", lap=25,
        now=item.observed_at + timedelta(days=1),
    ) is not None


def test_api_observation_endpoint_and_explicit_unavailability(
    predictable_dataset, tmp_path: Path,
) -> None:
    path = tmp_path / "trace.jsonl"
    empty = TestClient(create_app(ApiSettings(), dataset=predictable_dataset))
    response = empty.get("/api/races/singapore/lap-trace?season=2026")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "LAP_TRACE_UNAVAILABLE"

    recorded = append_lap_checkpoint(path, sample())
    client = TestClient(create_app(
        ApiSettings(lap_trace_path=path), dataset=predictable_dataset,
    ))
    response = client.get("/api/races/singapore/lap-trace?season=2026&lap=25")
    assert response.status_code == 200
    body = response.json()
    assert body["checkpoint"]["lap"] == 25
    assert body["checkpoint"]["totalLaps"] == 62
    assert body["checkpoint"]["sourceType"] == "synthetic-fixture"
    assert body["recordSha256"] == recorded.record_sha256
    assert body["forecastStatus"] == "not-qualified"
    assert body["advisoryOnly"] is True
    assert "winner" not in body
    assert client.get("/api/races/singapore/lap-trace?season=2026&lap=24").status_code == 404
    assert client.get("/api/races/singapore/lap-trace?season=2025").status_code == 404
    assert client.get("/api/races/singapore/lap-trace").status_code == 422
    assert client.get("/api/races/singapore/lap-trace?season=2026&lap=0").status_code == 422

    altered = json.loads(path.read_text(encoding="utf-8"))
    altered["checkpoint"]["lap"] = 22
    path.write_text(json.dumps(altered) + "\n", encoding="utf-8")
    refused = client.get("/api/races/singapore/lap-trace?season=2026")
    assert refused.status_code == 503
    assert refused.json()["detail"]["code"] == "LAP_TRACE_TAMPERED"


def test_import_cli_requires_exact_retained_provider_bytes(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "ingest-lap-checkpoint.py"
    data = b'{"synthetic": true, "source": "fixture"}'
    source = tmp_path / "raw.json"
    source.write_bytes(data)
    snapshot = sample()
    source_hash = hashlib.sha256(data).hexdigest()
    spec = tmp_path / "checkpoint.json"
    spec.write_text(
        snapshot.model_copy(update={
            "source_payload_sha256": source_hash,
        }).model_dump_json(by_alias=True),
        encoding="utf-8",
    )
    trace = tmp_path / "trace.jsonl"
    cmd = [
        sys.executable, str(script), "--checkpoint", str(spec),
        "--source-payload", str(source), "--trace", str(trace),
    ]
    assert subprocess.run(cmd, capture_output=True, text=True).returncode == 0
    assert verify_lap_trace(trace)[0].checkpoint.source_payload_sha256 == source_hash
    wrong = tmp_path / "wrong.json"
    wrong.write_text("{}", encoding="utf-8")
    failed = subprocess.run(
        [sys.executable, str(script), "--checkpoint", str(spec),
         "--source-payload", str(wrong), "--trace", str(tmp_path / "other.jsonl")],
        capture_output=True, text=True,
    )
    assert failed.returncode != 0
    assert "hash" in failed.stderr.lower()
