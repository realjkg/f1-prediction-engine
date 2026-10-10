#!/usr/bin/env python3
"""Evaluate database-trained models on chronological F1 holdout seasons."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from f1engine.store_benchmark import evaluate_season


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default="data/training/f1-training.sqlite")
    parser.add_argument(
        "--season", type=int, action="append", required=True,
        help="Completed holdout season (repeat for additional seasons)",
    )
    parser.add_argument("--report", help="Optional JSON report file")
    args = parser.parse_args(argv)
    with sqlite3.connect(args.store) as db:
        data = {
            "method": "expanding-window, strictly earlier race-result labels; qualifying-conditional challengers are retrospective unless timestamp verified",
            "source": "verified SQL training_samples",
            "results": [
                asdict(evaluate_season(db, season, method=model))
                for season in args.season
                for model in ("form", "logit", "gbm", "logit-qual", "gbm-qual")
            ],
        }
    report = json.dumps(data, indent=2) + "\n"
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
    print(report, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
