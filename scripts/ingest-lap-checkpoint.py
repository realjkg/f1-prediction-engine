#!/usr/bin/env python3
"""Ingest normalized, source-backed lap data; no network or prediction.

Keep the underlying permitted provider response as a separate raw file.
The hash check proves this manifest names those exact bytes, not that those
bytes are authentic or that an operator has any specific data rights.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from f1engine.lap_trace import LapCheckpoint, append_lap_checkpoint  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument(
        "--source-payload", type=Path, required=True,
        help="Retained provider response: must match sourcePayloadSha256",
    )
    parser.add_argument("--trace", type=Path, required=True)
    args = parser.parse_args(argv)
    digest = hashlib.sha256(args.source_payload.read_bytes()).hexdigest()
    data = json.loads(args.checkpoint.read_text(encoding="utf-8"))
    checkpoint = LapCheckpoint.model_validate(data)
    if checkpoint.source_payload_sha256 != digest:
        parser.error("source bytes do not match claimed sourcePayloadSha256")
    record = append_lap_checkpoint(args.trace, checkpoint)
    print(json.dumps({
        "season": checkpoint.season,
        "raceId": checkpoint.race_id,
        "lap": checkpoint.lap,
        "traceSha256": record.record_sha256,
        "sourceType": checkpoint.source_type,
        "forecastStatus": record.forecast_status,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
