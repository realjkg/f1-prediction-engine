"""Within-session qualifying form, always normalized for session conditions.

Avoid interpreting raw Q1→Q3 elapsed-time changes as driver skill: track grip,
tyres and weather can evolve between sessions. Instead compare each driver's
gap to the *quickest driver in that same session*, and then the change in gap
as Q1/Q2 progress to Q3. All inputs come exclusively from the qualifying
source table, not target-race results.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from f1engine.training_store import TrainingSample

SESSION_FEATURE_NAMES = (
    "q1_gap_to_session_fastest_ms",
    "q2_gap_to_session_fastest_ms",
    "q1_to_q3_relative_improvement_ms",
    "q2_to_q3_relative_improvement_ms",
)

SessionKey = tuple[int, int, str]


def session_progression_index(
    db: sqlite3.Connection,
) -> dict[SessionKey, tuple[float | None, ...]]:
    """Same-race qualifying only; session-relative pace avoids track evolution."""
    sessions: dict[tuple[int, int], list[tuple[str, int | None, int | None, int | None]]] = {}
    for season, round_number, driver, q1, q2, q3 in db.execute(
        "SELECT season, round, driver_id, q1_ms, q2_ms, q3_ms "
        "FROM qualifying ORDER BY season, round, driver_id"
    ):
        sessions.setdefault((season, round_number), []).append(
            (driver, q1, q2, q3)
        )
    features: dict[SessionKey, tuple[float | None, ...]] = {}
    for (season, round_number), drivers in sessions.items():
        best_times = tuple(
            min((row[i] for row in drivers if row[i] is not None), default=None)
            for i in (1, 2, 3)
        )
        for driver, q1, q2, q3 in drivers:
            raw = (q1, q2, q3)
            gaps = tuple(
                float(current - fastest)
                if current is not None and fastest is not None else None
                for current, fastest in zip(raw, best_times, strict=True)
            )
            q1_gap, q2_gap, q3_gap = gaps
            features[(season, round_number, driver)] = (
                q1_gap, q2_gap,
                q1_gap - q3_gap
                if q1_gap is not None and q3_gap is not None else None,
                q2_gap - q3_gap
                if q2_gap is not None and q3_gap is not None else None,
            )
    return features


def with_session_progression(
    samples: list[TrainingSample],
    index: dict[SessionKey, tuple[float | None, ...]],
) -> list[TrainingSample]:
    """Append observations without changing any outcome labels."""
    missing: tuple[float | None, ...] = (None,) * len(SESSION_FEATURE_NAMES)
    return [
        replace(
            row,
            values=row.values + index.get(
                (row.season, row.round, row.driver_id), missing
            ),
        )
        for row in samples
    ]
