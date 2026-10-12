"""Live OpenF1 ingest: raw topic events in, immutable per-lap artifacts out.

Transport-free on purpose. `scripts/run-live-ingest.py` owns the TLS 1.3 MQTT
connection and hands every message to `LiveIngestor.handle`; tests feed it
payloads directly. For each message the ingestor

1. validates and normalizes it with the same checks as the offline collector,
2. appends it to a durable, source-preserving spool (so any live run can be
   replayed later with the offline scripts),
3. and, when the leader has completed a new lap, projects an as-of checkpoint
   at that message's capture time and writes the same immutable trace,
   scenario and (with a frozen pre-race prior) fusion artifacts that the
   read-only API already serves.

Nothing here forecasts on its own, promotes a model, or touches the network.
The fusion weight stays whatever the operator froze; it is unqualified until
the chronological gate has run on real races (docs/INRACE_ACCURACY.md).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from f1engine.inrace_pipeline import (
    project_and_record,
    write_fusion_artifacts,
)
from f1engine.lap_trace import LapTraceError
from f1engine.live_prior import PreRacePrior
from f1engine.openf1_feed import normalize_message
from f1engine.openf1_projection import MAX_EVENTS, _completed_lap

# Topics whose projection keeps only the newest document per driver (or
# overall), so older revisions are semantically dead weight. Compacting them
# keeps a full race inside the projection's event budget without changing any
# projected value.
_LATEST_PER_DRIVER = frozenset(("position", "intervals"))
_LATEST_OVERALL = frozenset(("weather",))
# The projection ignores "stints" (see openf1_projection), so do not keep it.
_PROJECTED_TOPICS = ("position", "intervals", "laps", "pit", "race_control", "weather")


@dataclass(frozen=True)
class LapEmission:
    """One new immutable checkpoint written by the ingestor."""

    lap: int
    checkpoint_sha256: str
    scenario_status: str
    fused: bool
    captured_at: datetime


@dataclass
class IngestStats:
    received: int = 0
    duplicates: int = 0
    other_session: int = 0
    rejected: int = 0
    refusals: int = 0
    last_refusal: str | None = None
    last_rejection: str | None = None


@dataclass
class _Held:
    packet: dict[str, object]
    record: dict[str, object]
    order: tuple[str, int]


@dataclass
class LiveIngestor:
    session_key: int
    season: int
    race_id: str
    total_laps: int
    entrants: tuple[int, ...]
    trace_path: Path
    artifact_root: Path
    spool_path: Path
    rights_evidence: str
    prior: PreRacePrior | None = None
    scenario_weight: float = 0.5
    trials: int = 2000
    stats: IngestStats = field(default_factory=IngestStats)
    last_lap: int = 1
    finished: bool = False
    _seen: set[tuple[str, int]] = field(default_factory=set)
    _held: dict[str, dict[object, _Held]] = field(default_factory=dict)
    _leader_laps: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.rights_evidence.strip():
            raise ValueError("live ingest requires a recorded rights reference")
        if len(self.entrants) < 2 or len(set(self.entrants)) != len(self.entrants):
            raise ValueError("verified, unique entrant list required")
        if not 0 <= self.scenario_weight <= 1:
            raise ValueError("scenario weight must lie in [0, 1]")
        self.spool_path.parent.mkdir(parents=True, exist_ok=True)

    # -- ingest ----------------------------------------------------------

    def handle(self, topic: str, payload: bytes, captured_at: datetime) -> LapEmission | None:
        """Process one MQTT message. Returns an emission when a lap checkpoint lands."""
        try:
            packet = normalize_message(topic, payload, self.session_key, captured_at)
        except ValueError as exc:
            # Visible, never silent: counted and kept for the operator log.
            self.stats.rejected += 1
            self.stats.last_rejection = str(exc)
            return None
        if packet is None:
            self.stats.other_session += 1
            return None
        identity = (topic, int(packet["providerSequence"]))  # type: ignore[call-overload]
        if identity in self._seen:
            self.stats.duplicates += 1
            return None
        self._seen.add(identity)
        self._append_spool(packet)
        self.stats.received += 1
        group = topic.removeprefix("v1/")
        record = json.loads(str(packet["rawPayloadText"]))
        self._hold(group, packet, record, captured_at)
        if group == "laps":
            return self._maybe_emit(captured_at)
        return None

    def _append_spool(self, packet: dict[str, object]) -> None:
        line = json.dumps(packet, sort_keys=True, separators=(",", ":")) + "\n"
        with self.spool_path.open("a", encoding="utf-8") as spool:
            spool.write(line)
            spool.flush()
            os.fsync(spool.fileno())

    def _hold(
        self, group: str, packet: dict[str, object],
        record: dict[str, object], captured_at: datetime,
    ) -> None:
        if group not in _PROJECTED_TOPICS:
            return
        when = record.get("date")
        order = (str(when) if isinstance(when, str) else captured_at.astimezone(UTC).isoformat(),
                 int(packet["providerSequence"]))  # type: ignore[call-overload]
        bucket = self._held.setdefault(group, {})
        if group in _LATEST_PER_DRIVER:
            key: object = record.get("driver_number")
        elif group in _LATEST_OVERALL:
            key = "all"
        else:
            key = (packet["providerSequence"], packet["providerKey"])
        old = bucket.get(key)
        if old is None or order >= old.order:
            bucket[key] = _Held(packet, record, order)
        if group == "laps":
            self._note_lap(record)

    def _note_lap(self, record: dict[str, object]) -> None:
        car, number = record.get("driver_number"), record.get("lap_number")
        if car in self.entrants and type(number) is int and _completed_lap(record) is not None:
            self._leader_laps[car] = max(self._leader_laps.get(car, 0), number)  # type: ignore[index]

    # -- projection ------------------------------------------------------

    def _bundle(self) -> bytes:
        events: dict[str, list[dict[str, object]]] = {topic: [] for topic in _PROJECTED_TOPICS}
        total = 0
        for topic in _PROJECTED_TOPICS:
            rows = sorted(self._held.get(topic, {}).values(), key=lambda held: held.order)
            events[topic] = [held.packet for held in rows]
            total += len(rows)
        if total > MAX_EVENTS:
            raise LapTraceError("live source exceeds the projection event budget")
        bundle = {"session_key": self.session_key, "events": events}
        return json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _leader(self) -> int | None:
        rows = self._held.get("position", {})
        for held in rows.values():
            car = held.record.get("driver_number")
            if held.record.get("position") == 1 and car in self.entrants:
                return int(car)  # type: ignore[call-overload]
        return None

    def _maybe_emit(self, captured_at: datetime) -> LapEmission | None:
        leader = self._leader()
        if leader is None:
            return None
        completed = self._leader_laps.get(leader, 0)
        if completed >= self.total_laps:
            self.finished = True
            return None
        lap = completed + 1
        if lap < 2 or lap <= self.last_lap:
            return None
        try:
            record, artifact = project_and_record(
                self._bundle(), trace_path=self.trace_path, artifact_root=self.artifact_root,
                season=self.season, race_id=self.race_id, session_key=self.session_key,
                lap=lap, total_laps=self.total_laps, cutoff=captured_at,
                captured_at=captured_at, entrant_numbers=self.entrants,
                source_type="licensed-live", rights_evidence=self.rights_evidence,
                trials=self.trials,
            )
        except LapTraceError as exc:
            # Incomplete field, lead change at the line, stale gaps: wait for
            # the next lap document. Never fill the gap with inferred data.
            self.stats.refusals += 1
            self.stats.last_refusal = str(exc)
            return None
        self.last_lap = lap
        fused = False
        if self.prior is not None and artifact.scenario is not None:
            try:
                write_fusion_artifacts(
                    self.artifact_root, record, artifact, self.prior,
                    scenario_weight=self.scenario_weight,
                )
                fused = True
            except ValueError as exc:
                self.stats.refusals += 1
                self.stats.last_refusal = f"fusion refused: {exc}"
        return LapEmission(
            lap=lap, checkpoint_sha256=record.record_sha256,
            scenario_status=artifact.status, fused=fused, captured_at=captured_at,
        )
