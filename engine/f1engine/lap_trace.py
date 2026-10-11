"""Time-stamped, append-only lap observations for licensed race-state replay.

This is a capture and provenance layer, not a trained race forecast. It never
fetches network data, infers missing laps, or reads a race's final classification.
Hashes detect changes within the stored local trace; they do not authenticate
a provider or certify that a data license exists.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from f1engine.wire import WireModel


class LapTraceError(ValueError):
    """A snapshot or its saved evidence does not meet the trace contract."""

    code = "LAP_TRACE_INVALID"


class LapTraceTampered(LapTraceError):
    code = "LAP_TRACE_TAMPERED"


class DriverOnTrack(WireModel):
    driver_number: int = Field(ge=1, le=999)
    position: int = Field(ge=1, le=30)
    gap_to_leader_seconds: float | None = Field(default=None, ge=0)
    tire_compound: str | None = None
    tire_age_laps: int | None = Field(default=None, ge=0)
    pit_stops: int | None = Field(default=None, ge=0)
    last_lap_seconds: float | None = Field(default=None, gt=0)

    @field_validator("gap_to_leader_seconds", "last_lap_seconds")
    @classmethod
    def finite_seconds(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("timing must be finite")
        return value


class LapCheckpoint(WireModel):
    """Observed running order and source metadata, not an expected finish."""

    season: int = Field(ge=1950, le=2100)
    race_id: str = Field(min_length=1, max_length=100)
    session_key: int = Field(ge=1)
    lap: int = Field(ge=1)
    total_laps: int = Field(ge=1)
    observed_at: datetime
    captured_at: datetime
    provider: str = Field(min_length=1, max_length=120)
    source_type: Literal["licensed-live", "historical-archive", "synthetic-fixture"]
    rights_evidence: str | None = Field(default=None, max_length=240)
    source_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    track_status: Literal["GREEN", "VSC", "SC", "RED", "UNKNOWN"] = "UNKNOWN"
    track_condition: Literal["dry", "mixed", "wet", "unknown"] = "unknown"
    running_order: tuple[DriverOnTrack, ...] = Field(min_length=2)
    unavailable_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_observation(self) -> LapCheckpoint:
        if self.lap > self.total_laps:
            raise ValueError("lap cannot exceed race distance")
        if self.observed_at.tzinfo is None or self.captured_at.tzinfo is None:
            raise ValueError("observation timestamps must be timezone-aware")
        observed = self.observed_at.astimezone(UTC)
        captured = self.captured_at.astimezone(UTC)
        if observed > captured:
            raise ValueError("observation must be available at capture time")
        if self.source_type == "licensed-live":
            if not self.rights_evidence:
                raise ValueError("live source requires rights evidence reference")
            if captured - observed > timedelta(seconds=120):
                raise ValueError("live checkpoint is stale at capture")
        positions = [d.position for d in self.running_order]
        numbers = [d.driver_number for d in self.running_order]
        if len(set(positions)) != len(positions) or len(set(numbers)) != len(numbers):
            raise ValueError("duplicate running position or driver")
        if 1 not in positions:
            raise ValueError("leader position missing; partial field cannot be scored")
        if self.running_order != tuple(sorted(self.running_order, key=lambda d: d.position)):
            raise ValueError("running order must be position-sorted")
        for driver in self.running_order:
            if driver.position == 1 and driver.gap_to_leader_seconds not in (None, 0):
                raise ValueError("leader cannot have a positive gap to itself")
        if len(set(self.unavailable_fields)) != len(self.unavailable_fields):
            raise ValueError("unavailable field names must be distinct")
        return self


class LapTraceRecord(WireModel):
    checkpoint: LapCheckpoint
    previous_sha256: str | None = None
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    forecast_status: Literal["not-qualified"] = "not-qualified"
    advisory_only: Literal[True] = True


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(checkpoint: LapCheckpoint, prev: str | None) -> str:
    return hashlib.sha256(_canonical({
        "checkpoint": checkpoint.model_dump(mode="json", by_alias=True),
        "previousSha256": prev,
        "recordSha256": None,
        "forecastStatus": "not-qualified",
        "advisoryOnly": True,
    })).hexdigest()


def verify_lap_trace(path: Path) -> list[LapTraceRecord]:
    """Verify every hash and chronological boundary before serving a record."""
    if not path.exists():
        return []
    records: list[LapTraceRecord] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, start=1):
                if not line.strip():
                    raise LapTraceTampered(f"blank trace line {number}")
                record = LapTraceRecord.model_validate_json(line)
                expected_prev = records[-1].record_sha256 if records else None
                if record.previous_sha256 != expected_prev or record.record_sha256 != _digest(
                    record.checkpoint, expected_prev
                ):
                    raise LapTraceTampered(f"invalid lap trace hash at line {number}")
                if records:
                    previous = records[-1].checkpoint
                    current = record.checkpoint
                    if (
                        previous.season, previous.race_id, previous.session_key,
                        previous.total_laps,
                    ) != (
                        current.season, current.race_id, current.session_key,
                        current.total_laps,
                    ):
                        raise LapTraceTampered("trace mixes races or sessions")
                    if current.lap < previous.lap or current.observed_at <= previous.observed_at:
                        raise LapTraceTampered("trace event time is not monotonic")
                    if current.captured_at < previous.captured_at:
                        raise LapTraceTampered("trace capture clock moved backward")
                records.append(record)
    except (OSError, ValueError) as error:
        if isinstance(error, LapTraceError):
            raise
        raise LapTraceTampered(f"unverifiable trace: {error}") from error
    return records


def append_lap_checkpoint(path: Path, checkpoint: LapCheckpoint) -> LapTraceRecord:
    """Durable append. One collector must exclusively own each trace file."""
    records = verify_lap_trace(path)
    if records:
        previous = records[-1].checkpoint
        if (
            previous.season, previous.race_id, previous.session_key,
            previous.total_laps,
        ) != (
            checkpoint.season, checkpoint.race_id, checkpoint.session_key,
            checkpoint.total_laps,
        ):
            raise LapTraceError("different event: create a separate trace")
        if checkpoint.lap < previous.lap or checkpoint.observed_at <= previous.observed_at:
            raise LapTraceError("snapshot is older than previous evidence")
        if checkpoint.captured_at < previous.captured_at:
            raise LapTraceError("capture clock moved backward")
    prev_hash = records[-1].record_sha256 if records else None
    record = LapTraceRecord(
        checkpoint=checkpoint, previous_sha256=prev_hash,
        record_sha256=_digest(checkpoint, prev_hash),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(record.model_dump_json(by_alias=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return record


def get_lap_observation(
    path: Path, *, season: int, race_id: str, lap: int | None = None,
    now: datetime | None = None,
) -> LapTraceRecord | None:
    """Return exact-lap replay or latest live state, after full-chain verification.

    Live latest-state queries refuse observations older than 120 seconds.
    Historical exact-lap replay is allowed and remains explicitly time-stamped.
    """
    records = verify_lap_trace(path)
    candidates = [
        record for record in records
        if (record.checkpoint.season, record.checkpoint.race_id) == (season, race_id)
        and (lap is None or record.checkpoint.lap == lap)
    ]
    if not candidates:
        return None
    latest = candidates[-1]
    if latest.checkpoint.source_type == "licensed-live" and lap is None:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise LapTraceError("current time must carry a timezone")
        age = current.astimezone(UTC) - latest.checkpoint.observed_at.astimezone(UTC)
        if age > timedelta(seconds=120) or age < timedelta(seconds=-5):
            raise LapTraceError("live checkpoint is stale or clock is invalid")
    return latest
