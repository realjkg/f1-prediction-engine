"""Append-only prediction ledger — sha256-chained, advisory-only.

Contract (spec, engine/f1engine/evidence): every prediction is a schema-valid
record with advisoryOnly: true, declared dataLimitations, and recordSha256
chained to the previous record. Verification walks the chain and detects
tampering. Backtest results are ledger records too.
"""

from pathlib import Path

LEDGER_SCHEMA_VERSION = 1


def append_record(ledger_path: Path, record: dict[str, object]) -> str:
    """Append one hash-chained record; returns the record's sha256."""
    raise NotImplementedError("ledger is implemented by the evidence task")


def verify_chain(ledger_path: Path) -> bool:
    """Recompute the chain; False on any tampering or gap."""
    raise NotImplementedError("ledger is implemented by the evidence task")
