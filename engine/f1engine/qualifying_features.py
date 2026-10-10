"""Observed post-qualifying features; never inferred from classified race results.

This is a *qualifying-conditional historical replay*, not a certified
timestamped live forecast. Jolpica qualifying rows lack authoritative
publication timestamps and final FIA grid-penalty data. Model promotion
requires a separate source with signed pre-race as-of evidence.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from f1engine.training_store import TrainingSample

QUALIFYING_FEATURE_NAMES = (
    "qualifying_position",
    "q3_gap_to_pole_ms",
    "q3_gap_to_teammate_ms",
)

QualifyingKey = tuple[int, int, str]


def qualifying_feature_index(
    db: sqlite3.Connection,
) -> dict[QualifyingKey, tuple[float | None, float | None, float | None]]:
    """Use only source `qualifying`, never `results.grid` or result labels."""
    race_rows: dict[tuple[int, int], list[tuple[str, str, int | None, int | None]]] = {}
    for season, round_number, driver_id, constructor_id, pos, q3 in db.execute(
        "SELECT season, round, driver_id, constructor_id, position, q3_ms "
        "FROM qualifying ORDER BY season, round, driver_id"
    ):
        race_rows.setdefault((season, round_number), []).append(
            (driver_id, constructor_id, pos, q3)
        )

    features: dict[
        QualifyingKey, tuple[float | None, float | None, float | None]
    ] = {}
    for (season, round_number), drivers in race_rows.items():
        q3_times = [q3 for _, _, _, q3 in drivers if q3 is not None]
        fastest = min(q3_times) if q3_times else None
        for driver_id, constructor_id, position, q3 in drivers:
            team_q3s = [
                peer_q3 for peer_id, peer_team, _, peer_q3 in drivers
                if peer_id != driver_id and peer_team == constructor_id
                and peer_q3 is not None
            ]
            teammate = min(team_q3s) if team_q3s else None
            features[(season, round_number, driver_id)] = (
                float(position) if position is not None else None,
                float(q3 - fastest) if q3 is not None and fastest is not None else None,
                float(q3 - teammate) if q3 is not None and teammate is not None else None,
            )
    return features


def with_qualifying(
    samples: list[TrainingSample],
    index: dict[QualifyingKey, tuple[float | None, float | None, float | None]],
) -> list[TrainingSample]:
    """Append qualifying-only observed features, keeping labels unchanged."""
    empty = (None, None, None)
    return [
        replace(
            row,
            values=row.values + index.get((row.season, row.round, row.driver_id), empty),
        )
        for row in samples
    ]
