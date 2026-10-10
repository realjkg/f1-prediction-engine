"""Versioned, offline SQLite training store for F1 model research.

The database is an auditable materialization of hash-verified source snapshots,
as-of feature vectors, and out-of-time backtests. It never trains by itself
and never changes the model's weights on read or via a live API request.

Crucially, supervised examples are selected with a strictly earlier round
boundary: there is no interface here to join the target race's label into its
own predictive features.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from f1engine.backtest import BacktestResult, aggregate_rounds
from f1engine.features import build_asof_features
from f1engine.ingestion import PinnedDataset

SCHEMA_VERSION = 1
ENSEMBLE_MODEL_ID = "ensemble"


class ImmutableRecordConflict(ValueError):
    """A dataset/model revision already exists with different evidence."""


_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS dataset_versions (
    dataset_digest TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    seasons TEXT NOT NULL,
    as_of_date TEXT,
    provenance_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS races (
    dataset_digest TEXT NOT NULL REFERENCES dataset_versions(dataset_digest),
    season INTEGER NOT NULL,
    round INTEGER NOT NULL,
    race_id TEXT NOT NULL,
    circuit_id TEXT NOT NULL,
    race_date TEXT NOT NULL,
    PRIMARY KEY (dataset_digest, season, round)
);
CREATE TABLE IF NOT EXISTS race_results (
    dataset_digest TEXT NOT NULL,
    season INTEGER NOT NULL,
    round INTEGER NOT NULL,
    driver_id TEXT NOT NULL,
    constructor_id TEXT NOT NULL,
    finish_position INTEGER,
    grid_position INTEGER,
    points REAL NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (dataset_digest, season, round, driver_id),
    FOREIGN KEY (dataset_digest, season, round)
        REFERENCES races(dataset_digest, season, round)
);
CREATE TABLE IF NOT EXISTS qualifying (
    dataset_digest TEXT NOT NULL,
    season INTEGER NOT NULL,
    round INTEGER NOT NULL,
    driver_id TEXT NOT NULL,
    grid_qualification_position INTEGER,
    q1_ms INTEGER,
    q2_ms INTEGER,
    q3_ms INTEGER,
    PRIMARY KEY (dataset_digest, season, round, driver_id),
    FOREIGN KEY (dataset_digest, season, round)
        REFERENCES races(dataset_digest, season, round)
);
CREATE TABLE IF NOT EXISTS feature_rows (
    dataset_digest TEXT NOT NULL,
    season INTEGER NOT NULL,
    round INTEGER NOT NULL,
    driver_id TEXT NOT NULL,
    features_json TEXT NOT NULL,
    feature_boundary TEXT NOT NULL DEFAULT 'strictly_prior_round',
    PRIMARY KEY (dataset_digest, season, round, driver_id),
    FOREIGN KEY (dataset_digest, season, round)
        REFERENCES races(dataset_digest, season, round)
);
CREATE TABLE IF NOT EXISTS model_runs (
    dataset_digest TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    season INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    scored_rounds INTEGER NOT NULL,
    skipped_rounds INTEGER NOT NULL,
    PRIMARY KEY (dataset_digest, model_revision, season),
    FOREIGN KEY (dataset_digest) REFERENCES dataset_versions(dataset_digest)
);
CREATE TABLE IF NOT EXISTS probabilities (
    dataset_digest TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    season INTEGER NOT NULL,
    round INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    driver_id TEXT NOT NULL,
    win_probability REAL NOT NULL CHECK (win_probability BETWEEN 0 AND 1),
    podium_probability REAL NOT NULL CHECK (podium_probability BETWEEN 0 AND 1),
    PRIMARY KEY (dataset_digest, model_revision, season, round, model_id, driver_id),
    FOREIGN KEY (dataset_digest, model_revision, season)
        REFERENCES model_runs(dataset_digest, model_revision, season)
);
CREATE INDEX IF NOT EXISTS idx_feature_round
    ON feature_rows(dataset_digest, season, round);
CREATE INDEX IF NOT EXISTS idx_results_round
    ON race_results(dataset_digest, season, round);
CREATE INDEX IF NOT EXISTS idx_probability_round
    ON probabilities(dataset_digest, model_revision, season, round);
"""


def canonical_json(value: Any) -> str:
    """Identical serializations for identical inputs and repeatable imports."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _insert_immutable(
    db: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    values: tuple[Any, ...],
    primary_key: tuple[str, ...],
) -> None:
    """Insert once; an identical retry is fine, a revision collision is not."""
    # Table and column identifiers are internal literals, never user input.
    all_columns = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    where = " AND ".join(f"{key}=?" for key in primary_key)
    keyed_values = tuple(values[columns.index(key)] for key in primary_key)
    previous = db.execute(
        f"SELECT {all_columns} FROM {table} WHERE {where}", keyed_values
    ).fetchone()
    if previous is not None:
        if tuple(previous) != values:
            raise ImmutableRecordConflict(
                f"conflicting {table} row at keys {primary_key}={keyed_values}"
            )
        return
    db.execute(
        f"INSERT INTO {table} ({all_columns}) VALUES ({placeholders})", values
    )


class TrainingStore:
    """Local persistent research store; one writer at a time, no network."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(_SCHEMA)
        self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> TrainingStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def import_dataset(self, dataset: PinnedDataset) -> None:
        """Persist verified historical facts and as-of features immutably."""
        digest = dataset.dataset_sha256
        provenance = dataset.provenance.model_dump(mode="json")
        as_of = getattr(dataset.provenance.snapshot, "asOfDate", None)
        with self.db:
            _insert_immutable(
                self.db, "dataset_versions",
                ("dataset_digest", "dataset_id", "seasons", "as_of_date", "provenance_json"),
                (digest, dataset.dataset_id, dataset.provenance.snapshot.seasons,
                 as_of, canonical_json(provenance)), ("dataset_digest",),
            )
            for race in dataset.races:
                _insert_immutable(
                    self.db, "races",
                    ("dataset_digest", "season", "round", "race_id", "circuit_id", "race_date"),
                    (digest, race.season, race.round, race.race_id,
                     race.circuit_id, race.date),
                    ("dataset_digest", "season", "round"),
                )
            for row in dataset.results:
                _insert_immutable(
                    self.db, "race_results",
                    ("dataset_digest", "season", "round", "driver_id", "constructor_id",
                     "finish_position", "grid_position", "points", "status"),
                    (digest, row.season, row.round, row.driver_id, row.constructor_id,
                     row.position, row.grid, float(row.points), row.status),
                    ("dataset_digest", "season", "round", "driver_id"),
                )
            for row in dataset.qualifying:
                _insert_immutable(
                    self.db, "qualifying",
                    ("dataset_digest", "season", "round", "driver_id",
                     "grid_qualification_position", "q1_ms", "q2_ms", "q3_ms"),
                    (digest, row.season, row.round, row.driver_id, row.position,
                     row.q1_ms, row.q2_ms, row.q3_ms),
                    ("dataset_digest", "season", "round", "driver_id"),
                )
            for row in build_asof_features(dataset).rows:
                _insert_immutable(
                    self.db, "feature_rows",
                    ("dataset_digest", "season", "round", "driver_id", "features_json"),
                    (digest, row.season, row.round, row.driver_id,
                     canonical_json(row.model_dump(mode="json"))),
                    ("dataset_digest", "season", "round", "driver_id"),
                )

    def training_examples_before(
        self, dataset_digest: str, season: int, round_number: int
    ) -> list[tuple[int, int, str, str, int | None]]:
        """Return features plus labels only from races before the requested round.

        The postrace results grid is never used to create target-round
        features. A stricter session-time ledger is needed before a
        post-qualifying *pre-race* model may use target-round qualifying.
        """
        return self.db.execute(
            """SELECT f.season, f.round, f.driver_id, f.features_json,
                      r.finish_position
               FROM feature_rows f JOIN race_results r
                 ON f.dataset_digest = r.dataset_digest
                AND f.season = r.season
                AND f.round = r.round
                AND f.driver_id = r.driver_id
               WHERE f.dataset_digest = ?
                 AND (f.season < ? OR (f.season = ? AND f.round < ?))
               ORDER BY f.season, f.round, f.driver_id""",
            (dataset_digest, season, season, round_number),
        ).fetchall()

    def record_backtest(
        self, dataset: PinnedDataset, result: BacktestResult, model_revision: str
    ) -> None:
        """Append per-driver probabilities and measured outcomes by revision.

        A changed model must use a new model_revision: this store never
        overwrites prior predictions or pretends old probabilities are new.
        """
        if not model_revision.strip():
            raise ValueError("model_revision is required")
        digest = dataset.dataset_sha256
        metrics = {
            model: metric.model_dump(mode="json")
            for model, metric in aggregate_rounds(result.rounds).items()
        }
        with self.db:
            _insert_immutable(
                self.db, "model_runs",
                ("dataset_digest", "model_revision", "season", "metrics_json",
                 "scored_rounds", "skipped_rounds"),
                (digest, model_revision, result.target_season, canonical_json(metrics),
                 len(result.rounds), len(result.skipped)),
                ("dataset_digest", "model_revision", "season"),
            )
            for race in result.rounds:
                distributions = [
                    (prediction.model_id, prediction.winner, prediction.podium)
                    for prediction in race.predictions
                ]
                distributions.append(
                    (ENSEMBLE_MODEL_ID, race.verdict.winner, race.verdict.podium)
                )
                for model_id, win, podium in distributions:
                    for driver_id in sorted(win):
                        _insert_immutable(
                            self.db, "probabilities",
                            ("dataset_digest", "model_revision", "season", "round",
                             "model_id", "driver_id", "win_probability",
                             "podium_probability"),
                            (digest, model_revision, race.season, race.round,
                             model_id, driver_id, win[driver_id], podium[driver_id]),
                            ("dataset_digest", "model_revision", "season", "round",
                             "model_id", "driver_id"),
                        )

    def inventory(self) -> dict[str, int]:
        """Bounded local counts for a reproducible training-data inventory."""
        return {
            table: self.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "dataset_versions", "races", "race_results", "qualifying",
                "feature_rows", "model_runs", "probabilities",
            )
        }
