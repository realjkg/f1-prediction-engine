"""Point-in-time F1 training store built from independently verified snapshots.

The SQLite database is a *materialization*, never the source of race truth.
Snapshots are SHA-256 checked by load_snapshot; all labels come from completed
races strictly before the supplied cutoff. Rebuild it when new verified
snapshots arrive, rather than mutating rows during a prediction.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from f1engine.features import AsOfFeatureRow, build_asof_features
from f1engine.ingestion import PinnedDataset, load_snapshot

STORE_SCHEMA_VERSION = 1
FEATURE_NAMES = (
    "starts", "form_finish_mean", "form_finish_mean_all", "q_best_ms",
    "q_delta_teammate_ms", "q_delta_pole_ms", "team_points_mean",
    "track_finish_mean",
)

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE datasets (
    dataset_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, seasons TEXT NOT NULL,
    generated_at TEXT NOT NULL
);
CREATE TABLE races (
    season INTEGER NOT NULL, round INTEGER NOT NULL, race_id TEXT NOT NULL,
    race_date TEXT NOT NULL, circuit_id TEXT NOT NULL, circuit_name TEXT NOT NULL,
    name TEXT NOT NULL, dataset_sha256 TEXT NOT NULL,
    PRIMARY KEY(season, round)
);
CREATE TABLE results (
    season INTEGER NOT NULL, round INTEGER NOT NULL, driver_id TEXT NOT NULL,
    constructor_id TEXT NOT NULL, position INTEGER, grid INTEGER, points REAL NOT NULL,
    laps INTEGER NOT NULL, status TEXT NOT NULL,
    PRIMARY KEY(season, round, driver_id),
    FOREIGN KEY(season, round) REFERENCES races(season, round)
);
CREATE TABLE qualifying (
    season INTEGER NOT NULL, round INTEGER NOT NULL, driver_id TEXT NOT NULL,
    constructor_id TEXT NOT NULL, position INTEGER,
    q1_ms INTEGER, q2_ms INTEGER, q3_ms INTEGER,
    PRIMARY KEY(season, round, driver_id),
    FOREIGN KEY(season, round) REFERENCES races(season, round)
);
CREATE TABLE training_samples (
    season INTEGER NOT NULL, round INTEGER NOT NULL, race_date TEXT NOT NULL,
    driver_id TEXT NOT NULL, constructor_id TEXT NOT NULL,
    starts INTEGER NOT NULL, form_finish_mean REAL, form_finish_mean_all REAL,
    q_best_ms INTEGER, q_delta_teammate_ms REAL, q_delta_pole_ms REAL,
    team_points_mean REAL, track_finish_mean REAL,
    won INTEGER NOT NULL, podium INTEGER NOT NULL,
    PRIMARY KEY(season, round, driver_id),
    FOREIGN KEY(season, round, driver_id)
        REFERENCES results(season, round, driver_id)
);
CREATE INDEX samples_asof_idx ON training_samples(season, round);
CREATE INDEX samples_driver_idx ON training_samples(driver_id, season, round);
CREATE TABLE model_evaluations (
    run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
    model_id TEXT NOT NULL, holdout_season INTEGER NOT NULL,
    training_cutoff TEXT NOT NULL, dataset_fingerprint TEXT NOT NULL,
    races_scored INTEGER NOT NULL, winner_hit_rate REAL NOT NULL,
    mean_brier REAL NOT NULL, notes TEXT NOT NULL DEFAULT ''
);
"""


@dataclass(frozen=True)
class TrainingSample:
    season: int
    round: int
    driver_id: str
    values: tuple[float | None, ...]
    won: int
    podium: int


def _combine(snapshots: list[PinnedDataset], cutoff: date) -> tuple[PinnedDataset, dict]:
    races: dict[tuple[int, int], object] = {}
    result_rows = []
    qualifying_rows = []
    sprint_rows = []
    drivers = {}
    constructors = {}
    origin: dict[tuple[int, int], str] = {}
    for snapshot in snapshots:
        for race in snapshot.races:
            key = (race.season, race.round)
            if key in races:
                raise ValueError(f"overlapping snapshots at {key}: refuse ambiguous provenance")
            races[key] = race
            origin[key] = snapshot.dataset_sha256
        for result in snapshot.results:
            race = races[(result.season, result.round)]
            if race.date >= cutoff.isoformat():
                raise ValueError("future/same-day race result exceeds training as-of cutoff")
            result_rows.append(result)
        qualifying_rows.extend(snapshot.qualifying)
        sprint_rows.extend(snapshot.sprints)
        for driver in snapshot.drivers:
            drivers[driver.driver_id] = driver
        for constructor in snapshot.constructors:
            constructors[constructor.constructor_id] = constructor
    if not snapshots:
        raise ValueError("at least one signed snapshot is required")
    combined = replace(
        snapshots[0], races=tuple(races[key] for key in sorted(races)),
        results=tuple(result_rows), qualifying=tuple(qualifying_rows),
        sprints=tuple(sprint_rows), drivers=tuple(drivers.values()),
        constructors=tuple(constructors.values()),
    )
    return combined, origin


def _sample_values(row: AsOfFeatureRow) -> tuple:
    return tuple(getattr(row, key) for key in FEATURE_NAMES)


def build_training_store(
    snapshot_dirs: list[Path], output: Path, *, as_of: date
) -> dict[str, int]:
    """Write a replace-atomically materialized DB; refuse unsourced outcomes."""
    snapshots = [load_snapshot(path) for path in snapshot_dirs]
    combined, origin = _combine(snapshots, as_of)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    try:
        with NamedTemporaryFile(
            prefix="f1-store-", suffix=".sqlite", dir=output.parent, delete=False
        ) as tmp:
            tmp_name = tmp.name
        with sqlite3.connect(tmp_name) as db:
            db.executescript(SCHEMA)
            db.executemany("INSERT INTO metadata VALUES (?, ?)", [
                ("schema_version", str(STORE_SCHEMA_VERSION)),
                ("as_of_exclusive", as_of.isoformat()),
                ("source_count", str(len(snapshots))),
            ])
            db.executemany("INSERT INTO datasets VALUES (?, ?, ?, ?)", [
                (
                    s.dataset_id, s.dataset_sha256, s.provenance.snapshot.seasons,
                    s.provenance.generatedAt,
                )
                for s in snapshots
            ])
            db.executemany("INSERT INTO races VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                (r.season, r.round, r.race_id, r.date, r.circuit_id, r.circuit_name, r.name,
                 origin[(r.season, r.round)])
                for r in combined.races
            ])
            db.executemany("INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                (r.season, r.round, r.driver_id, r.constructor_id, r.position, r.grid,
                 r.points, r.laps, r.status)
                for r in combined.results
            ])
            db.executemany("INSERT INTO qualifying VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                (r.season, r.round, r.driver_id, r.constructor_id, r.position,
                 r.q1_ms, r.q2_ms, r.q3_ms)
                for r in combined.qualifying
            ])
            labels = {(r.season, r.round, r.driver_id): r.position for r in combined.results}
            race_dates = {(r.season, r.round): r.date for r in combined.races}
            rows = []
            for f in build_asof_features(combined).rows:
                key = (f.season, f.round, f.driver_id)
                if key not in labels:
                    continue
                position = labels[key]
                rows.append((
                    f.season, f.round, race_dates[(f.season, f.round)], f.driver_id,
                    f.constructor_id, *_sample_values(f), int(position == 1),
                    int(position is not None and position <= 3),
                ))
            db.executemany(
                "INSERT INTO training_samples VALUES (" + ",".join(["?"] * 15) + ")", rows
            )
            db.commit()
        os.replace(tmp_name, output)
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return {"datasets": len(snapshots), "races": len(combined.races),
            "results": len(combined.results), "samples": len(rows)}


def training_rows_before(
    db: sqlite3.Connection, season: int, round_number: int
) -> list[TrainingSample]:
    """Fit only on prior rounds. Query ordering is deterministic."""
    cols = ", ".join(FEATURE_NAMES)
    sql = (
        "SELECT season, round, driver_id, " + cols + ", won, podium "
        "FROM training_samples WHERE season < ? OR (season = ? AND round < ?) "
        "ORDER BY season, round, driver_id"
    )
    return [
        TrainingSample(
            season=row[0], round=row[1], driver_id=row[2],
            values=tuple(row[3:3 + len(FEATURE_NAMES)]),
            won=row[-2], podium=row[-1],
        )
        for row in db.execute(sql, (season, season, round_number))
    ]
