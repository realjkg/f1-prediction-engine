"""Shared snapshot identity — table names and canonical hashing.

The refresh script (writer) and the ingestion loaders (verifier) must agree
on what the snapshot is: which tables it contains and how the integrity
hashes are computed. Both import this module so the definition cannot drift.
"""

import hashlib
from pathlib import Path

SNAPSHOT_TABLE_NAMES: tuple[str, ...] = (
    "races",
    "results",
    "qualifying",
    "sprints",
    "drivers",
    "constructors",
)


def sha256_hex(data: bytes) -> str:
    """sha256 of raw bytes, hex-encoded."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """sha256 of a file's bytes, hex-encoded (streamed)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def combined_table_hash(table_hashes: dict[str, str]) -> str:
    """Hash the per-table hashes in canonical (sorted-name) order.

    Adding, removing, or altering any table changes this value — it is the
    dataset-level sha256 recorded in provenance.json.
    """
    canonical = "\n".join(
        f"{name}:{table_hashes[name]}" for name in sorted(table_hashes)
    )
    return sha256_hex(canonical.encode("utf-8"))
