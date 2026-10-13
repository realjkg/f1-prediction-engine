"""A clearly synthetic race streamed through the real live ingest path.

The public Vercel demo cannot hold an MQTT connection, but its Live Lab should
still show what a live checkpoint, scenario and pre-race fusion look like. This
module invents a small race ("demo-synthetic"), feeds it message by message
through `LiveIngestor`, and leaves the same immutable trace and artifacts a real
session would. Every checkpoint is stamped `synthetic-fixture`; none of it is
an F1 result, a forecast of a real race, or licensed provider data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from f1engine.live_ingest import LapEmission, LiveIngestor
from f1engine.live_prior import PreRacePrior

DEMO_RACE_ID = "demo-synthetic"
DEMO_SEASON = 2026
DEMO_SESSION_KEY = 990001
DEMO_TOTAL_LAPS = 20
DEMO_LAPS_PLAYED = 10
DEMO_START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

# (driver number, seconds off the pace per lap, pre-race win probability)
_FIELD: tuple[tuple[int, float, float], ...] = (
    (1, 0.00, 0.34), (16, 0.03, 0.22), (4, 0.05, 0.16), (44, 0.08, 0.11),
    (55, 0.10, 0.08), (63, 0.14, 0.05), (81, 0.20, 0.03), (11, 0.28, 0.01),
)
_BASE_LAP = 90.0
_PIT_CAR, _PIT_LAP, _PIT_LOSS = 16, 5, 21.0


def _lap_time(car: int, offset: float, lap: int) -> float:
    wobble = ((car * 37 + lap * 11) % 9 - 4) * 0.09
    time = _BASE_LAP + offset + wobble - 0.012 * lap
    return time + (_PIT_LOSS if (car, lap) == (_PIT_CAR, _PIT_LAP) else 0.0)


def demo_prior() -> PreRacePrior:
    return PreRacePrior(
        season=DEMO_SEASON, race_id=DEMO_RACE_ID, session_key=DEMO_SESSION_KEY,
        model_revision="synthetic-demo-prior-v1",
        model_artifact_sha256="d" * 64, dataset_sha256="e" * 64,
        source_issued_at=DEMO_START - timedelta(days=1),
        frozen_at=DEMO_START - timedelta(hours=1),
        race_start_at=DEMO_START - timedelta(minutes=10),
        driver_win_probabilities={car: prob for car, _, prob in _FIELD},
    )


def build_demo_live_fixture(root: Path) -> list[LapEmission]:
    """Write `trace.jsonl`, `artifacts/` and `spool.jsonl` under `root`."""
    root.mkdir(parents=True, exist_ok=True)
    if (root / "trace.jsonl").exists():
        raise FileExistsError("demo live fixture already built; traces are append-only")
    ingestor = LiveIngestor(
        session_key=DEMO_SESSION_KEY, season=DEMO_SEASON, race_id=DEMO_RACE_ID,
        total_laps=DEMO_TOTAL_LAPS, entrants=tuple(car for car, _, _ in _FIELD),
        trace_path=root / "trace.jsonl", artifact_root=root / "artifacts",
        spool_path=root / "spool.jsonl", rights_evidence=None,
        prior=demo_prior(), scenario_weight=0.35, trials=500,
        source_type="synthetic-fixture",
    )
    cumulative = {car: 0.0 for car, _, _ in _FIELD}
    events: list[tuple[datetime, int, str, dict[str, object]]] = [
        (DEMO_START, 0, "race_control",
         {"date": DEMO_START.isoformat(), "flag": "GREEN", "scope": "Track",
          "category": "Flag", "message": "GREEN LIGHT - PIT EXIT OPEN"}),
        (DEMO_START, 1, "weather", {"date": DEMO_START.isoformat(), "rainfall": 0}),
    ]
    for lap in range(1, DEMO_LAPS_PLAYED + 1):
        ends: dict[int, datetime] = {}
        for car, offset, _ in _FIELD:
            start_offset = cumulative[car]
            cumulative[car] += _lap_time(car, offset, lap)
            ends[car] = DEMO_START + timedelta(seconds=cumulative[car])
            events.append((ends[car], 5, "laps", {
                "driver_number": car, "lap_number": lap,
                "lap_duration": round(cumulative[car] - start_offset, 3),
                "date_start": (DEMO_START + timedelta(seconds=start_offset)).isoformat(),
            }))
            if (car, lap) == (_PIT_CAR, _PIT_LAP):
                events.append((ends[car] - timedelta(seconds=30), 4, "pit", {
                    "driver_number": car, "lap_number": lap, "pit_duration": _PIT_LOSS,
                    "date": (ends[car] - timedelta(seconds=30)).isoformat(),
                }))
        order = sorted(cumulative, key=lambda car: cumulative[car])
        leader_end = ends[order[0]]
        stamp = leader_end - timedelta(seconds=3)
        for place, car in enumerate(order, start=1):
            gap = round(cumulative[car] - cumulative[order[0]], 3)
            events.append((stamp, 2, "position", {
                "driver_number": car, "position": place, "date": stamp.isoformat()}))
            events.append((stamp, 3, "intervals", {
                "driver_number": car, "gap_to_leader": gap, "date": stamp.isoformat()}))

    sequence = 5000
    emissions: list[LapEmission] = []
    for when, _, topic, body in sorted(events, key=lambda event: (event[0], event[1])):
        sequence += 1
        payload = json.dumps({
            "session_key": DEMO_SESSION_KEY, "_id": sequence,
            "_key": f"demo-{topic}-{sequence}", **body,
        }).encode()
        emission = ingestor.handle(f"v1/{topic}", payload, when + timedelta(seconds=1))
        if emission is not None:
            emissions.append(emission)
    return emissions
