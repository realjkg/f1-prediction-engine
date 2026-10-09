"""Ingestion tests: valid load, refusals, hash stability.

The tamper and refusal cases run against a mini snapshot built by the real
refresh pipeline (conftest), so writer and verifier are always exercised
against each other. One test anchors the committed repository snapshot.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from f1engine.dataset import sha256_file
from f1engine.ingestion import (
    CredentialMaterialRefused,
    DataSnapshotMismatch,
    SnapshotHashMismatch,
    SnapshotProvenanceMissing,
    SnapshotSchemaInvalid,
    SnapshotVersionMismatch,
    SnapshotVersionMissing,
    load_snapshot,
    read_dataset_version,
)

REPO_SNAPSHOT = Path(__file__).resolve().parents[2] / "data" / "snapshot"


def test_committed_pinned_snapshot_loads() -> None:
    dataset = load_snapshot(REPO_SNAPSHOT)

    assert dataset.dataset_id == "2026.10.0"
    assert dataset.dataset_sha256 == dataset.provenance.snapshot.sha256
    assert len(dataset.races) == 107
    assert len(dataset.results) == 2139
    assert len(dataset.qualifying) == 2138
    assert len(dataset.sprints) == 360
    assert len(dataset.drivers) == 36
    assert len(dataset.constructors) == 14
    # Rows are validated closed models with typed fields.
    first = dataset.races[0]
    assert first.season == 2020
    assert dataset.limitations  # limitations declared, never empty


def test_every_committed_table_matches_its_declared_hash() -> None:
    dataset = load_snapshot(REPO_SNAPSHOT)
    for name, table in dataset.provenance.tables.items():
        path = REPO_SNAPSHOT / f"{name}.parquet"
        assert sha256_file(path) == table.sha256, name
        assert table.rows > 0 or name == "sprints"


def test_load_is_stable_across_repeated_calls() -> None:
    first = load_snapshot(REPO_SNAPSHOT)
    second = load_snapshot(REPO_SNAPSHOT)

    assert first.dataset_sha256 == second.dataset_sha256
    assert first.results == second.results
    assert first.qualifying == second.qualifying
    assert sha256_file(REPO_SNAPSHOT / "results.parquet") == (
        first.provenance.tables["results"].sha256
    )


def test_refuses_unversioned_snapshot(mini_snapshot: Path) -> None:
    (mini_snapshot / "DATASET_VERSION").unlink()

    with pytest.raises(SnapshotVersionMissing) as raised:
        load_snapshot(mini_snapshot)
    assert raised.value.code == "DATA_SNAPSHOT_VERSION_MISSING"


def test_refuses_empty_version_file(mini_snapshot: Path) -> None:
    (mini_snapshot / "DATASET_VERSION").write_text("\n", encoding="utf-8")

    with pytest.raises(DataSnapshotMismatch):
        read_dataset_version(mini_snapshot)


def test_refuses_version_mismatch(mini_snapshot: Path) -> None:
    (mini_snapshot / "DATASET_VERSION").write_text("9999.0.0\n", encoding="utf-8")

    with pytest.raises(SnapshotVersionMismatch) as raised:
        load_snapshot(mini_snapshot)
    assert raised.value.code == "DATA_SNAPSHOT_VERSION_MISMATCH"


def test_refuses_missing_provenance(mini_snapshot: Path) -> None:
    (mini_snapshot / "provenance.json").unlink()

    with pytest.raises(SnapshotProvenanceMissing):
        load_snapshot(mini_snapshot)


def test_refuses_tampered_table_bytes(mini_snapshot: Path) -> None:
    results_path = mini_snapshot / "results.parquet"
    tampered = results_path.read_bytes()[:-1] + b"\x00"  # flip the last byte
    results_path.write_bytes(tampered)

    with pytest.raises(SnapshotHashMismatch) as raised:
        load_snapshot(mini_snapshot)
    assert raised.value.code == "DATA_SNAPSHOT_HASH_MISMATCH"
    assert "results.parquet" in str(raised.value)


def test_refuses_swapped_table_files(mini_snapshot: Path) -> None:
    # A table moved to another name fails per-table hash verification.
    shutil.copy(mini_snapshot / "drivers.parquet", mini_snapshot / "races.parquet")

    with pytest.raises(SnapshotHashMismatch):
        load_snapshot(mini_snapshot)


def test_refuses_combined_hash_mismatch(mini_snapshot: Path) -> None:
    provenance_path = mini_snapshot / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    # Per-table hashes stay correct; only the dataset-level hash drifts.
    provenance["snapshot"]["sha256"] = "0" * 64
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

    with pytest.raises(SnapshotHashMismatch):
        load_snapshot(mini_snapshot)


def test_refuses_credential_material_in_provenance(mini_snapshot: Path) -> None:
    provenance_path = mini_snapshot / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["sources"][0]["api_key"] = "sk-live-should-never-appear"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

    with pytest.raises(CredentialMaterialRefused) as raised:
        load_snapshot(mini_snapshot)
    assert raised.value.code == "DATA_SNAPSHOT_CREDENTIAL_REFUSED"


def test_refuses_drifted_table_with_stale_provenance(mini_snapshot: Path) -> None:
    # Rebuild one table with an extra column, keeping provenance stale:
    # per-table hash must fail before schema checks see the drift.
    import pyarrow as pa
    import pyarrow.parquet as pq

    races_path = mini_snapshot / "races.parquet"
    table = pq.read_table(races_path)
    drifted = table.append_column(
        pa.field("weather_note", pa.string()),
        pa.array(["sunny"] * table.num_rows),
    )
    pq.write_table(drifted, races_path)

    with pytest.raises(SnapshotHashMismatch):
        load_snapshot(mini_snapshot)


def test_refuses_schema_drift_even_when_hashes_match(
    mini_snapshot: Path, tmp_path: Path
) -> None:
    """The closed schema rejects an extra column even when hashes agree.

    Rebuilds the whole snapshot with a drifted races table so the recorded
    hashes match the drifted bytes — proving schema validation is a separate,
    independent guard, not something hashing alone provides.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    from f1engine.dataset import combined_table_hash

    drifted_path = tmp_path / "drifted-races.parquet"
    table = pq.read_table(mini_snapshot / "races.parquet")
    drifted = table.append_column(
        pa.field("weather_note", pa.string()),
        pa.array(["sunny"] * table.num_rows),
    )
    pq.write_table(drifted, drifted_path)

    provenance_path = mini_snapshot / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["tables"]["races"]["sha256"] = sha256_file(drifted_path)
    hashes = {
        name: (
            sha256_file(drifted_path)
            if name == "races"
            else provenance["tables"][name]["sha256"]
        )
        for name in provenance["tables"]
    }
    provenance["snapshot"]["sha256"] = combined_table_hash(hashes)
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    shutil.copy(drifted_path, mini_snapshot / "races.parquet")

    with pytest.raises(SnapshotSchemaInvalid) as raised:
        load_snapshot(mini_snapshot)
    assert raised.value.code == "DATA_SNAPSHOT_SCHEMA_INVALID"
