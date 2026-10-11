"""Validated, hash-bound loaders over the pinned dataset snapshot.

Contract (spec, engine/f1engine/ingestion): Pydantic-validated loaders read
only the pinned parquet snapshot under data/snapshot/, record provenance and
sha256 on load, and re-verify the recorded hashes against the bytes on EVERY
load — refusing unversioned, mismatched, or tampered data with the
DATA_SNAPSHOT_MISMATCH error family. Any payload that looks like credential
material is refused before it is parsed into rows. Jolpica/OpenF1 refresh
adapters are explicit offline steps (scripts/refresh-data.py), never a
runtime dependency.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from f1engine.dataset import SNAPSHOT_TABLE_NAMES, combined_table_hash, sha256_file

VERSION_FILE = "DATASET_VERSION"
PROVENANCE_FILE = "provenance.json"

# Credential-material scan: any mapping key matching this pattern refuses the
# load — the snapshot must never carry secrets (LZ ingest.ts refusal pattern).
_CREDENTIAL_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|credential|api[_\-]?key)", re.IGNORECASE
)


class DataSnapshotMismatch(RuntimeError):
    """Base of the snapshot refusal family (code DATA_SNAPSHOT_MISMATCH)."""

    code = "DATA_SNAPSHOT_MISMATCH"


class SnapshotVersionMissing(DataSnapshotMismatch):
    """DATASET_VERSION is absent — the snapshot is unversioned."""

    code = "DATA_SNAPSHOT_VERSION_MISSING"


class SnapshotProvenanceMissing(DataSnapshotMismatch):
    """provenance.json is absent — nothing declares what this data is."""

    code = "DATA_SNAPSHOT_PROVENANCE_MISSING"


class SnapshotVersionMismatch(DataSnapshotMismatch):
    """DATASET_VERSION and provenance.datasetId disagree."""

    code = "DATA_SNAPSHOT_VERSION_MISMATCH"


class SnapshotTableMissing(DataSnapshotMismatch):
    """A declared snapshot table file is not on disk."""

    code = "DATA_SNAPSHOT_TABLE_MISSING"


class SnapshotHashMismatch(DataSnapshotMismatch):
    """Table bytes or the combined hash do not match the provenance record."""

    code = "DATA_SNAPSHOT_HASH_MISMATCH"


class SnapshotSchemaInvalid(DataSnapshotMismatch):
    """Rows failed the closed per-table schema."""

    code = "DATA_SNAPSHOT_SCHEMA_INVALID"


class CredentialMaterialRefused(DataSnapshotMismatch):
    """A payload key looks like credential material — refused, never parsed."""

    code = "DATA_SNAPSHOT_CREDENTIAL_REFUSED"


def _reject_credential_keys(payload: object, where: str) -> None:
    """Recursive refusal scan (LZ ingest.ts pattern): walk dicts and lists."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and _CREDENTIAL_KEY_PATTERN.search(key):
                raise CredentialMaterialRefused(
                    f"{where}: refused key {key!r} — looks like credential material"
                )
            _reject_credential_keys(value, where)
    elif isinstance(payload, list):
        for item in payload:
            _reject_credential_keys(item, where)


class RaceRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    season: int = Field(ge=1950, le=2100)
    round: int = Field(ge=1, le=100)
    race_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    circuit_id: str = Field(min_length=1)
    circuit_name: str = Field(min_length=1)
    country: str = Field(min_length=1)
    locality: str = Field(min_length=1)


class ResultRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    season: int = Field(ge=1950, le=2100)
    round: int = Field(ge=1, le=100)
    race_id: str = Field(min_length=1)
    position: int | None = Field(default=None, ge=1, le=999)
    position_text: str = Field(min_length=1)
    points: float = Field(ge=0.0)
    driver_id: str = Field(min_length=1)
    constructor_id: str = Field(min_length=1)
    grid: int | None = Field(default=None, ge=0, le=999)
    laps: int = Field(ge=0)
    status: str = Field(min_length=1)
    finish_time_ms: int | None = Field(default=None, ge=0)


class QualifyingRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    season: int = Field(ge=1950, le=2100)
    round: int = Field(ge=1, le=100)
    race_id: str = Field(min_length=1)
    position: int | None = Field(default=None, ge=1, le=999)
    driver_id: str = Field(min_length=1)
    constructor_id: str = Field(min_length=1)
    q1_ms: int | None = Field(default=None, ge=0)
    q2_ms: int | None = Field(default=None, ge=0)
    q3_ms: int | None = Field(default=None, ge=0)


class SprintRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    season: int = Field(ge=1950, le=2100)
    round: int = Field(ge=1, le=100)
    race_id: str = Field(min_length=1)
    position: int | None = Field(default=None, ge=1, le=999)
    position_text: str = Field(min_length=1)
    points: float = Field(ge=0.0)
    driver_id: str = Field(min_length=1)
    constructor_id: str = Field(min_length=1)
    status: str = Field(min_length=1)


class DriverRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    driver_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    given_name: str = Field(min_length=1)
    family_name: str = Field(min_length=1)
    nationality: str = Field(min_length=1)


class ConstructorRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    constructor_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    nationality: str = Field(min_length=1)


ROW_MODELS: dict[str, type[BaseModel]] = {
    "races": RaceRow,
    "results": ResultRow,
    "qualifying": QualifyingRow,
    "sprints": SprintRow,
    "drivers": DriverRow,
    "constructors": ConstructorRow,
}


class TableProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SourceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    role: str = Field(min_length=1)
    baseUrl: str = Field(min_length=1)
    endpoints: list[str]
    fetchedAt: str | None = None
    license: str = Field(min_length=1)


class SnapshotIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seasons: str = Field(min_length=1)
    format: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    asOfDate: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class Provenance(BaseModel):
    """The closed schema of provenance.json (writer: scripts/refresh-data.py)."""

    model_config = ConfigDict(extra="forbid")

    schemaVersion: int = Field(ge=1)
    datasetId: str = Field(min_length=1)
    generatedAt: str = Field(min_length=1)
    snapshot: SnapshotIdentity
    tables: dict[str, TableProvenance]
    sources: list[SourceProvenance]
    dataLimitations: list[str]


@dataclass(frozen=True)
class PinnedDataset:
    """The validated snapshot: hashes verified, rows schema-checked."""

    dataset_id: str
    dataset_sha256: str
    provenance: Provenance
    races: tuple[RaceRow, ...]
    results: tuple[ResultRow, ...]
    qualifying: tuple[QualifyingRow, ...]
    sprints: tuple[SprintRow, ...]
    drivers: tuple[DriverRow, ...]
    constructors: tuple[ConstructorRow, ...]

    @property
    def limitations(self) -> tuple[str, ...]:
        return tuple(self.provenance.dataLimitations)


def read_dataset_version(snapshot_dir: Path) -> str:
    """Read DATASET_VERSION, refusing an unversioned snapshot."""
    version_path = snapshot_dir / VERSION_FILE
    if not version_path.exists():
        raise SnapshotVersionMissing(
            f"unversioned snapshot: {version_path} not found"
        )
    version = version_path.read_text(encoding="utf-8").strip()
    if not version:
        raise SnapshotVersionMissing(f"unversioned snapshot: {version_path} is empty")
    return version


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SnapshotSchemaInvalid(f"{path} is not readable JSON: {error}") from error
    if not isinstance(payload, dict):
        raise SnapshotSchemaInvalid(f"{path} must contain a JSON object")
    return payload


def _load_and_validate_provenance(snapshot_dir: Path) -> Provenance:
    provenance_path = snapshot_dir / PROVENANCE_FILE
    if not provenance_path.exists():
        raise SnapshotProvenanceMissing(
            f"no provenance record: {provenance_path} not found"
        )
    raw = _read_json(provenance_path)
    _reject_credential_keys(raw, PROVENANCE_FILE)
    try:
        return Provenance.model_validate(raw)
    except ValidationError as error:
        raise SnapshotSchemaInvalid(
            f"provenance.json failed its closed schema: {error}"
        ) from error


def verify_snapshot_hashes(snapshot_dir: Path, provenance: Provenance) -> None:
    """Byte-level verification of every table against the provenance record.

    Separated from row loading so tests (and the demo preflight) can verify
    integrity without paying for full row validation.
    """
    actual_hashes: dict[str, str] = {}
    for name in SNAPSHOT_TABLE_NAMES:
        table_path = snapshot_dir / f"{name}.parquet"
        if not table_path.exists():
            raise SnapshotTableMissing(f"missing snapshot table: {table_path}")
        declared = provenance.tables.get(name)
        if declared is None:
            raise SnapshotProvenanceMissing(
                f"provenance.json declares no table {name!r}"
            )
        actual_hashes[name] = sha256_file(table_path)
        if actual_hashes[name] != declared.sha256:
            raise SnapshotHashMismatch(
                f"{name}.parquet content hash {actual_hashes[name]} does not "
                f"match provenance {declared.sha256}"
            )
    combined = combined_table_hash(actual_hashes)
    if combined != provenance.snapshot.sha256:
        raise SnapshotHashMismatch(
            f"combined table hash {combined} does not match provenance "
            f"{provenance.snapshot.sha256}"
        )


def _load_table(
    snapshot_dir: Path, name: str, expected_sha256: str, expected_rows: int
) -> tuple:
    import pyarrow.parquet as pq

    table_path = snapshot_dir / f"{name}.parquet"
    if not table_path.exists():
        raise SnapshotTableMissing(f"missing snapshot table: {table_path}")

    actual_sha256 = sha256_file(table_path)
    if actual_sha256 != expected_sha256:
        raise SnapshotHashMismatch(
            f"{name}.parquet content hash {actual_sha256} does not match "
            f"provenance {expected_sha256}"
        )

    rows = pq.read_table(table_path).to_pylist()
    if len(rows) != expected_rows:
        raise SnapshotHashMismatch(
            f"{name}.parquet has {len(rows)} rows, provenance declares "
            f"{expected_rows}"
        )

    model = ROW_MODELS[name]
    for index, row in enumerate(rows):
        _reject_credential_keys(row, f"{name}.parquet row {index}")
    try:
        return tuple(model.model_validate(row) for row in rows)  # type: ignore[return-value]
    except ValidationError as error:
        raise SnapshotSchemaInvalid(
            f"{name}.parquet rows failed the closed {model.__name__} schema: {error}"
        ) from error


def load_snapshot(snapshot_dir: Path) -> PinnedDataset:
    """Load the pinned snapshot: verify version, hashes, then schema-rows.

    Every call re-hashes the bytes — trust is established per load, never
    assumed from a previous run. Raises the DATA_SNAPSHOT_MISMATCH family on
    any version, hash, schema, or credential refusal.
    """
    version = read_dataset_version(snapshot_dir)
    provenance = _load_and_validate_provenance(snapshot_dir)
    if version != provenance.datasetId:
        raise SnapshotVersionMismatch(
            f"DATASET_VERSION {version!r} does not match provenance datasetId "
            f"{provenance.datasetId!r}"
        )

    verify_snapshot_hashes(snapshot_dir, provenance)

    tables = {
        name: _load_table(
            snapshot_dir,
            name,
            provenance.tables[name].sha256,
            provenance.tables[name].rows,
        )
        for name in SNAPSHOT_TABLE_NAMES
    }
    return PinnedDataset(
        dataset_id=provenance.datasetId,
        dataset_sha256=provenance.snapshot.sha256,
        provenance=provenance,
        races=tables["races"],  # type: ignore[arg-type]
        results=tables["results"],  # type: ignore[arg-type]
        qualifying=tables["qualifying"],  # type: ignore[arg-type]
        sprints=tables["sprints"],  # type: ignore[arg-type]
        drivers=tables["drivers"],  # type: ignore[arg-type]
        constructors=tables["constructors"],  # type: ignore[arg-type]
    )
