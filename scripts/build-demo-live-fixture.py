#!/usr/bin/env python3
"""Build the synthetic Live Lab fixture for the container demo (build-time only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from f1engine.demo_live_fixture import DEMO_RACE_ID, build_demo_live_fixture  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    emissions = build_demo_live_fixture(args.output)
    print(json.dumps({
        "raceId": DEMO_RACE_ID, "sourceType": "synthetic-fixture",
        "checkpoints": [e.lap for e in emissions],
        "fusedLaps": [e.lap for e in emissions if e.fused],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
