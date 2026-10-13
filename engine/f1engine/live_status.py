"""Verified live-source readiness: persisted MQTT heartbeat plus evidence-bound checkpoint.

This module never opens an OpenF1 connection. It reports the operator's
actual private collector state and recorded evidence, without inventing
live timing or suggesting a scenario is calibrated inference.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field

from f1engine.inrace_pipeline import read_run_artifact
from f1engine.lap_trace import verify_lap_trace
from f1engine.wire import WireModel

HEARTBEAT_MAX_BYTES = 4096
HEARTBEAT_MAX_AGE = timedelta(seconds=40)
MESSAGE_MAX_AGE = timedelta(seconds=120)


class LiveStatusInvalid(ValueError):
    """Unverifiable operator heartbeat."""


class LiveStatusView(WireModel):
    feed_state: Literal["not-configured", "offline", "connected", "stale"]
    evidence_state: Literal["none", "replay", "fresh-checkpoint", "stale-checkpoint"]
    inference_state: Literal["unavailable", "conditional-research"]
    season: int
    race_id: str
    broker: Literal["openf1"] = "openf1"
    last_message_at: datetime | None = None
    last_checkpoint_at: datetime | None = None
    lap: int | None = None
    total_laps: int | None = None
    source_type: Literal["licensed-live", "historical-archive", "synthetic-fixture"] | None = None
    checkpoint_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    qualified_for_production: Literal[False] = False
    model_promoted: Literal[False] = False


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise LiveStatusInvalid("invalid live collector timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LiveStatusInvalid("invalid live collector timestamp") from exc
    if parsed.tzinfo is None:
        raise LiveStatusInvalid("collector timestamp has no timezone")
    return parsed.astimezone(UTC)


def live_status(
    *, season: int, race_id: str, trace_path: Path | None,
    artifact_root: Path | None, heartbeat_path: Path | None,
    now: datetime | None = None,
) -> LiveStatusView:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    state: Literal["not-configured", "offline", "connected", "stale"] = "not-configured"
    last_message: datetime | None = None
    broker_session: int | None = None

    if heartbeat_path is not None:
        state = "offline"
        if heartbeat_path.exists():
            raw = heartbeat_path.read_bytes()
            if not raw or len(raw) > HEARTBEAT_MAX_BYTES:
                raise LiveStatusInvalid("collector heartbeat exceeds limits")
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise LiveStatusInvalid("invalid collector heartbeat JSON") from exc
            if not isinstance(payload, dict) or payload.get("provider") != "openf1":
                raise LiveStatusInvalid("collector heartbeat source mismatch")
            if payload.get("season") != season or payload.get("raceId") != race_id:
                raise LiveStatusInvalid("collector heartbeat race mismatch")
            broker_session = payload.get("sessionKey")
            if type(broker_session) is not int or broker_session < 1:
                raise LiveStatusInvalid("collector session identity missing")
            last_update = _parse_utc(payload.get("updatedAt"))
            value = payload.get("lastMessageAt")
            last_message = _parse_utc(value) if value is not None else None
            if last_update > current + timedelta(seconds=5) or (
                last_message is not None and last_message > current + timedelta(seconds=5)
            ):
                raise LiveStatusInvalid("collector clock leads server clock")
            recent_heartbeat = current - last_update <= HEARTBEAT_MAX_AGE
            recent_message = (
                last_message is not None and current - last_message <= MESSAGE_MAX_AGE
            )
            state = (
                "connected" if payload.get("connected") is True
                and recent_heartbeat and recent_message
                else "stale" if payload.get("connected") is True
                else "offline"
            )

    result = LiveStatusView(
        feed_state=state, evidence_state="none", inference_state="unavailable",
        season=season, race_id=race_id, last_message_at=last_message,
    )
    if trace_path is None:
        return result

    records = verify_lap_trace(trace_path)
    observed = [
        row for row in records
        if row.checkpoint.season == season and row.checkpoint.race_id == race_id
    ]
    if not observed:
        return result

    latest = observed[-1]
    checkpoint = latest.checkpoint
    if broker_session is not None and checkpoint.session_key != broker_session:
        raise LiveStatusInvalid("collector heartbeat session differs from recorded lap")
    fresh = timedelta(seconds=-5) <= current - checkpoint.observed_at <= MESSAGE_MAX_AGE
    evidence = (
        "fresh-checkpoint" if checkpoint.source_type == "licensed-live" and fresh
        else "stale-checkpoint" if checkpoint.source_type == "licensed-live"
        else "replay"
    )
    inference: Literal["unavailable", "conditional-research"] = "unavailable"
    if artifact_root is not None:
        saved = read_run_artifact(
            artifact_root, season=season, race_id=race_id, lap=checkpoint.lap,
            checkpoint_sha256=latest.record_sha256,
        )
        if saved is not None and saved.status == "scenario":
            inference = "conditional-research"

    return LiveStatusView(
        feed_state=state,
        evidence_state=evidence,
        inference_state=inference,
        season=season,
        race_id=race_id,
        source_type=checkpoint.source_type,
        last_message_at=last_message,
        last_checkpoint_at=checkpoint.observed_at,
        lap=checkpoint.lap,
        total_laps=checkpoint.total_laps,
        checkpoint_sha256=latest.record_sha256,
    )
