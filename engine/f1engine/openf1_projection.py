"""As-of OpenF1 projection: verified provider records -> one lap checkpoint.

No final classification or current race outcomes are queried. The archived
endpoint "stints" may carry retrospective lap_end data without publication
time, so it is deliberately not used as an as-of fact for historical replay.
Timestamped source events at/before the operator-provided cutoff are the
only inputs. Source incompleteness must stay visible, never be filled in.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from f1engine.lap_trace import DriverOnTrack, LapCheckpoint, LapTraceError

MAX_EVENTS = 120000
TOPICS = frozenset(("position", "intervals", "laps", "pit", "stints", "race_control", "weather"))


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise LapTraceError("source event must contain an ISO timestamp")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise LapTraceError("invalid source timestamp") from error
    if timestamp.tzinfo is None:
        raise LapTraceError("source timestamps must include timezone")
    return timestamp.astimezone(UTC)


def _completed_lap(row: Mapping[str, object]) -> datetime | None:
    """A lap becomes usable only when completed, not when the car starts it."""
    start = row.get("date_start")
    duration = row.get("lap_duration")
    if start is None or duration is None:
        return None
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        return None
    if not math.isfinite(duration) or duration < 40 or duration > 400:
        return None
    return _time(start) + timedelta(seconds=duration)


def _event_time(
    topic: str, row: Mapping[str, object], captured: datetime | None,
) -> datetime | None:
    if topic == "laps":
        return _completed_lap(row)
    if row.get("date") is not None:
        return _time(row["date"])
    # Live source documents with no event-date are only known as-of capture.
    # Archived undated stints cannot provide a trustworthy as-of snapshot.
    return captured


def _rows(
    bundle: Mapping[str, object], cutoff: datetime, session_key: int,
) -> dict[str, list[tuple[datetime, dict[str, object]]]]:
    raw = bundle.get("events")
    if not isinstance(raw, dict) or set(raw) - TOPICS:
        raise LapTraceError("only allowlisted OpenF1 source event collections are accepted")
    result: dict[str, list[tuple[datetime, dict[str, object]]]] = {}
    total = 0
    for topic, records in raw.items():
        if not isinstance(records, list):
            raise LapTraceError(f"{topic} must contain a list")
        items: list[tuple[datetime, dict[str, object]]] = []
        for packet in records:
            total += 1
            if total > MAX_EVENTS:
                raise LapTraceError("source event budget exceeded")
            if not isinstance(packet, dict):
                raise LapTraceError("source row must be an object")
            captured: datetime | None = None
            if "rawPayloadText" in packet:
                if packet.get("topic") != "v1/" + topic:
                    raise LapTraceError("MQTT source topic does not match collection")
                captured = _time(packet.get("capturedAt"))
                text = packet["rawPayloadText"]
                if not isinstance(text, str):
                    raise LapTraceError("MQTT raw payload missing")
                raw_bytes = text.encode("utf-8")
                if hashlib.sha256(raw_bytes).hexdigest() != packet.get("rawPayloadSha256"):
                    raise LapTraceError("MQTT source payload digest mismatch")
                try:
                    record = json.loads(text)
                except json.JSONDecodeError as error:
                    raise LapTraceError("MQTT raw source not JSON") from error
                if not isinstance(record, dict):
                    raise LapTraceError("MQTT source object required")
                if captured > cutoff:
                    continue
                if record.get("_id") != packet.get("providerSequence"):
                    raise LapTraceError("MQTT sequence identity mismatch")
                if record.get("_key") != packet.get("providerKey"):
                    raise LapTraceError("MQTT document identity mismatch")
            else:
                record = packet
            if record.get("session_key") != session_key:
                raise LapTraceError("source collection mixes sessions")
            when = _event_time(topic, record, captured)
            if when is None:
                continue
            if when > cutoff or (captured is not None and captured > cutoff):
                continue
            if captured is not None and when > captured:
                raise LapTraceError("source event cannot occur after capture")
            items.append((when, record))
        # MQTT updates may publish multiple revisions of one provider
        # document. Retain the latest revision *available by the cutoff*,
        # not every delivery as a separate lap or pit event. Never collapse
        # unrelated source documents or invent missing sequence numbers.
        if any("_key" in item for _, item in items):
            revisions: dict[str, tuple[datetime, dict[str, object]]] = {}
            unkeyed: list[tuple[datetime, dict[str, object]]] = []
            for when, item in items:
                key = item.get("_key")
                if not isinstance(key, str) or not key:
                    unkeyed.append((when, item))
                    continue
                old = revisions.get(key)
                sequence = item.get("_id")
                prior_sequence = old[1].get("_id") if old else None
                if old is None or (
                    when, sequence if type(sequence) is int else -1
                ) >= (
                    old[0], prior_sequence if type(prior_sequence) is int else -1
                ):
                    revisions[key] = (when, item)
            items = unkeyed + list(revisions.values())
        items.sort(key=lambda item: item[0])
        result[topic] = items
    return result


def project_lap_checkpoint(
    raw_source: bytes, *,
    season: int, race_id: str, session_key: int, lap: int,
    total_laps: int, cutoff: datetime, entrant_numbers: tuple[int, ...],
    source_type: str, rights_evidence: str | None,
    captured_at: datetime,
) -> LapCheckpoint:
    """Project exact verified driver roster at lap N using no future records."""
    if cutoff.tzinfo is None or captured_at.tzinfo is None:
        raise LapTraceError("cutoff and capture must carry timezone")
    if cutoff > captured_at:
        raise LapTraceError("cannot project source evidence from the future")
    if len(entrant_numbers) < 2 or len(set(entrant_numbers)) != len(entrant_numbers):
        raise LapTraceError("verified, unique entrant list required")
    if len(entrant_numbers) > 24 or lap < 2 or lap > total_laps:
        raise LapTraceError("unsupported entrant field or lap")
    if len(raw_source) > 30_000_000:
        raise LapTraceError("source payload exceeds 30 MB budget")
    try:
        bundle = json.loads(raw_source)
    except (ValueError, UnicodeDecodeError) as error:
        raise LapTraceError("source bundle must be UTF-8 JSON") from error
    if not isinstance(bundle, dict) or bundle.get("session_key") != session_key:
        raise LapTraceError("source bundle session identity mismatch")
    by_topic = _rows(bundle, cutoff.astimezone(UTC), session_key)

    # Preserve only the last known position per confirmed entrant, not an
    # inferred full field. If the archive is incomplete, refuse projection.
    latest_position: dict[int, int] = {}
    for _, item in by_topic.get("position", []):
        car = item.get("driver_number")
        pos = item.get("position")
        if car in entrant_numbers and type(pos) is int and 1 <= pos <= 30:
            latest_position[car] = pos
    if set(latest_position) != set(entrant_numbers):
        raise LapTraceError("position feed does not cover verified entrant list")

    lap_history: dict[int, list[tuple[datetime, int, float]]] = {
        car: [] for car in entrant_numbers
    }
    completed_laps: dict[tuple[int, int], tuple[datetime, float]] = {}
    for ended, item in by_topic.get("laps", []):
        car, number, duration = (
            item.get("driver_number"),
            item.get("lap_number"),
            item.get("lap_duration"),
        )
        if car in entrant_numbers and type(number) is int and type(duration) in (int, float):
            if number <= lap and math.isfinite(duration):
                # Duplicate/revised lap documents must not count as extra
                # pace samples; only one completed lap per driver/number.
                completed_laps[(car, number)] = (ended, float(duration))
    for (car, number), (ended, duration) in completed_laps.items():
        lap_history[car].append((ended, number, duration))
    # 'Lap 25' convention: leader is in progress on lap 25, and 24 laps are
    # complete. Do not reconstruct a lap-25 view using evidence after lap 25.
    leader = next((car for car, pos in latest_position.items() if pos == 1), None)
    if leader is None or max((x[1] for x in lap_history[leader]), default=0) != lap - 1:
        raise LapTraceError("cutoff does not match in-progress lap boundary")

    latest_gaps: dict[int, tuple[datetime, float]] = {}
    for event_time, item in by_topic.get("intervals", []):
        car = item.get("driver_number")
        gap = item.get("gap_to_leader")
        if car not in entrant_numbers or gap is None:
            continue
        # '+1 LAP' etc cannot be safely converted to a time interval.
        if isinstance(gap, str):
            try:
                value = float(gap)
            except ValueError:
                continue
        elif type(gap) in (float, int):
            value = float(gap)
        else:
            continue
        if math.isfinite(value) and value >= 0:
            latest_gaps[car] = (event_time, value)

    pit_counts = dict.fromkeys(entrant_numbers, 0)
    seen_pits: set[tuple[object, object, object]] = set()
    for _, item in by_topic.get("pit", []):
        car = item.get("driver_number")
        if car not in pit_counts:
            continue
        # One pit visit can be delivered repeatedly or updated by the
        # provider. A repeated event is not another pit stop.
        identity = (car, item.get("lap_number"), item.get("date"))
        if identity not in seen_pits:
            seen_pits.add(identity)
            pit_counts[car] += 1

    status = "UNKNOWN"
    for _, item in by_topic.get("race_control", []):
        msg = str(item.get("message", "")).upper()
        category = str(item.get("category", "")).lower()
        flag = str(item.get("flag") or "").upper()
        if "RED FLAG" in msg or flag == "RED":
            status = "RED"
        elif "VIRTUAL SAFETY CAR" in msg or "VSC DEPLOYED" in msg:
            status = "VSC"
        elif "SAFETY CAR" in msg and "ENDING" not in msg and "IN THIS LAP" not in msg:
            status = "SC"
        elif flag == "GREEN" and (item.get("scope") == "Track" or category == "flag"):
            status = "GREEN"
    weather = "unknown"
    for _, item in by_topic.get("weather", []):
        rain = item.get("rainfall")
        if rain in (0, False):
            weather = "dry"
        elif rain in (1, True):
            weather = "wet"

    unavailable = {"tire_compound", "tire_age_laps"}
    runners: list[DriverOnTrack] = []
    for car, position in sorted(latest_position.items(), key=lambda item: item[1]):
        if car == leader:
            gap = 0.0
        else:
            value = latest_gaps.get(car)
            gap = (
                value[1]
                if value is not None and cutoff - value[0] <= timedelta(seconds=45)
                else None
            )
            if gap is None:
                unavailable.add("gap_to_leader_seconds")
        records = sorted(lap_history[car], key=lambda item: item[1])
        recent = tuple(x[2] for x in records[-3:])
        if len(recent) < 3:
            unavailable.add("recent_lap_seconds")
        runners.append(DriverOnTrack(
            driver_number=car, position=position, gap_to_leader_seconds=gap,
            pit_stops=pit_counts[car], last_lap_seconds=recent[-1] if recent else None,
            recent_lap_seconds=recent,
        ))
    if status == "UNKNOWN":
        unavailable.add("track_status")
    if weather == "unknown":
        unavailable.add("track_condition")
    return LapCheckpoint(
        season=season, race_id=race_id, session_key=session_key,
        lap=lap, total_laps=total_laps,
        observed_at=cutoff, captured_at=captured_at,
        provider="openf1",
        source_type=source_type, rights_evidence=rights_evidence,
        source_payload_sha256=hashlib.sha256(raw_source).hexdigest(),
        track_status=status, track_condition=weather,
        running_order=tuple(runners), unavailable_fields=tuple(sorted(unavailable)),
    )
