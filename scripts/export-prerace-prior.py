#!/usr/bin/env python3
"""Export a genuinely pre-race existing engine ledger prediction as a prior.

Refuses the historical demo when its prediction was generated after lights out.
A separate authenticated source must verify event start and driver-number map.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from f1engine.evidence import PredictionRecord, parsed_record, verify_chain  # noqa: E402
from f1engine.live_prior import prior_from_existing_engine_record  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--race-id", required=True)
    parser.add_argument("--session-key", type=int, required=True)
    parser.add_argument("--race-start", required=True)
    parser.add_argument(
        "--driver-map", type=Path, required=True,
        help='verified JSON mapping engine driver IDs to car numbers, e.g. {"x":16}',
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    verify_chain(args.ledger)
    if not args.ledger.exists():
        parser.error("verified ledger does not exist")
    records = [
        parsed_record(i, line)
        for i, line in enumerate(args.ledger.read_text(encoding="utf-8").splitlines())
        if line.strip()
    ]
    eligible = [
        record for record in records
        if isinstance(record, PredictionRecord)
        and record.race.season == args.season
        and record.race.race_id == args.race_id
    ]
    if len(eligible) != 1:
        parser.error("exactly one matching immutable prediction record is required")
    driver_map = json.loads(args.driver_map.read_text(encoding="utf-8"))
    if not isinstance(driver_map, dict) or not all(
        isinstance(name, str) and type(number) is int
        for name, number in driver_map.items()
    ):
        parser.error("driver map must be exact driver ID -> integer car number")
    prior = prior_from_existing_engine_record(
        eligible[0], season=args.season, race_id=args.race_id,
        session_key=args.session_key,
        race_start_at=datetime.fromisoformat(args.race_start.replace("Z", "+00:00")),
        driver_number_by_id=driver_map,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(prior.model_dump_json(by_alias=True) + "\n")
    print(json.dumps({
        "modelRevision": prior.model_revision,
        "datasetSha256": prior.dataset_sha256,
        "raceId": prior.race_id,
        "season": prior.season,
        "frozenAt": prior.frozen_at.isoformat(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
