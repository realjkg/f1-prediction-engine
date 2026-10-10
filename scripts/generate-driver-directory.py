#!/usr/bin/env python3
"""Generate the web client's driver directory from the pinned snapshot.

The UI needs driver codes and full names for display; those live in the
pinned dataset (data/snapshot/drivers.parquet), the same source the engine
reads. Regenerate after a dataset refresh:

    .venv/bin/python scripts/generate-driver-directory.py

Writes web/src/lib/driverDirectory.ts — a generated file; do not edit it by
hand. Missing snapshot is a hard error (no silent stale directory).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO / "data" / "snapshot" / "drivers.parquet"
TARGET = REPO / "web" / "src" / "lib" / "driverDirectory.ts"

HEADER = """\
/**
 * GENERATED FILE — do not edit by hand.
 * Generated from the pinned snapshot (data/snapshot/drivers.parquet) by
 * scripts/generate-driver-directory.py. Regenerate after a dataset refresh.
 */

import type { DriverIdentity } from "./drivers";
"""


def main() -> int:
    if not SNAPSHOT.exists():
        print(f"error: pinned snapshot not found at {SNAPSHOT}", file=sys.stderr)
        return 1
    table = pq.read_table(SNAPSHOT, columns=["driver_id", "code", "given_name", "family_name"])
    rows = sorted(table.to_pylist(), key=lambda row: str(row["driver_id"]))
    if not rows:
        print("error: pinned snapshot has no drivers", file=sys.stderr)
        return 1

    lines = [HEADER, "export const DRIVERS: Record<string, DriverIdentity> = {"]
    for row in rows:
        driver_id = str(row["driver_id"])
        code = str(row["code"])
        name = f"{row['given_name']} {row['family_name']}"
        lines.append(
            f'  {driver_id!r}: {{ driverId: {driver_id!r}, code: {code!r}, name: {name!r} }},'
        )
    lines.append("};")
    lines.append("")
    TARGET.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {TARGET} with {len(rows)} drivers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
