#!/usr/bin/env python3
"""Materialize a reproducible training database from hash-verified F1 snapshots."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from f1engine.training_store import build_training_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot", action="append", required=True,
        help="Verified parquet snapshot directory; repeat for disjoint seasons",
    )
    parser.add_argument("--as-of", required=True, help="Exclusive YYYY-MM-DD outcome cutoff")
    parser.add_argument("--output", default="data/training/f1-training.sqlite")
    args = parser.parse_args(argv)
    counts = build_training_store(
        [Path(path) for path in args.snapshot], Path(args.output),
        as_of=date.fromisoformat(args.as_of),
    )
    print(f"training store: {args.output} — {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
