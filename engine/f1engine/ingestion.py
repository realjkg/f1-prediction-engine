"""Validated loaders over the pinned dataset snapshot.

Contract (spec, engine/f1engine/ingestion): Pydantic-validated loaders read
only the pinned parquet snapshot under data/snapshot/, record provenance and
sha256 on load, and re-verify the recorded hash against the bytes on every
load — refusing unversioned or mismatched data with DataSnapshotMismatch.
Jolpica/OpenF1 refresh adapters are explicit offline steps, never a runtime
dependency.

Owned by the ingestion task; this scaffold fixes the seam and its failure
type.
"""

from pathlib import Path


class DataSnapshotMismatch(RuntimeError):
    """The snapshot on disk does not match the pinned provenance record."""


def load_snapshot(snapshot_dir: Path) -> dict[str, object]:
    """Load the pinned snapshot, verifying DATASET_VERSION and provenance hash.

    Returns the validated dataset tables (typed by the ingestion task).
    Raises DataSnapshotMismatch on any version or hash drift.
    """
    raise NotImplementedError("ingestion is implemented by the data task")
