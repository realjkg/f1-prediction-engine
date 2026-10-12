"""The UI must never mistake an absent or stale collector for live inference."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from f1engine.app import ApiSettings, create_app
from f1engine.live_status import LiveStatusInvalid, live_status


def heartbeat(path, *, season=2026, race="singapore", session=1234, connected=True,
              updated=None, last=None):
    now = datetime.now(UTC)
    path.write_text(json.dumps({
        "provider": "openf1", "season": season, "raceId": race,
        "sessionKey": session, "connected": connected,
        "updatedAt": (updated or now).isoformat(),
        "lastMessageAt": (last or now).isoformat(),
    }), encoding="utf-8")


def test_no_collector_or_trace_refuses_live_claim():
    status = live_status(
        season=2026, race_id="singapore", trace_path=None,
        artifact_root=None, heartbeat_path=None,
    )
    assert status.feed_state == "not-configured"
    assert status.evidence_state == "none"
    assert status.inference_state == "unavailable"
    assert status.qualified_for_production is False
    assert status.model_promoted is False


def test_connected_requires_fresh_real_message(tmp_path):
    status_file = tmp_path / "status.json"
    now = datetime.now(UTC)
    heartbeat(status_file)
    status = live_status(
        season=2026, race_id="singapore", trace_path=None,
        artifact_root=None, heartbeat_path=status_file, now=now,
    )
    assert status.feed_state == "connected"
    assert status.evidence_state == "none"
    assert status.lap is None
    assert status.inference_state == "unavailable"

    heartbeat(status_file, updated=now - timedelta(minutes=4),
              last=now - timedelta(minutes=5))
    status = live_status(
        season=2026, race_id="singapore", trace_path=None,
        artifact_root=None, heartbeat_path=status_file, now=now,
    )
    assert status.feed_state == "stale"


def test_mismatch_and_corruption_fail_closed(tmp_path):
    status_file = tmp_path / "status.json"
    heartbeat(status_file, race="monaco")
    with pytest.raises(LiveStatusInvalid, match="race mismatch"):
        live_status(season=2026, race_id="singapore", trace_path=None,
                    artifact_root=None, heartbeat_path=status_file)
    status_file.write_text("{", encoding="utf-8")
    with pytest.raises(LiveStatusInvalid, match="JSON"):
        live_status(season=2026, race_id="singapore", trace_path=None,
                    artifact_root=None, heartbeat_path=status_file)


def test_api_never_reports_connected_without_operator_source(predictable_dataset):
    client = TestClient(create_app(ApiSettings(), dataset=predictable_dataset))
    response = client.get("/api/live/status?season=2026&race_id=singapore")
    assert response.status_code == 200
    body = response.json()
    assert body["feedState"] == "not-configured"
    assert body["inferenceState"] == "unavailable"
    assert body["qualifiedForProduction"] is False
    assert body["modelPromoted"] is False
    assert body["lastMessageAt"] is None


def test_invalid_operator_heartbeat_returns_http_503(predictable_dataset, tmp_path):
    status_file = tmp_path / "status.json"
    status_file.write_text('{"provider":"other"}', encoding="utf-8")
    client = TestClient(create_app(
        ApiSettings(live_heartbeat_path=status_file), dataset=predictable_dataset,
    ))
    response = client.get("/api/live/status?season=2026&race_id=singapore")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "LIVE_STATUS_INVALID"
