#!/usr/bin/env python3
"""Rebuild a local, versioned training/evaluation store from a verified snapshot.

Examples:
  python3 scripts/build-training-store.py --season 2024
  python3 scripts/build-training-store.py --data-dir data/snapshot-fall-2026 --season 2026
  python3 scripts/build-training-store.py --season 2024 --revision challenger-grid-v2

No source data is fetched. This program never runs as an automatic live-model
updater; refresh upstream data explicitly and retain snapshot provenance.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "engine") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "engine"))

from f1engine.backtest import aggregate_rounds, run_backtest
from f1engine.ingestion import load_snapshot
from f1engine.training_store import TrainingStore

DEFAULT_WEIGHTS = {"m1-gbm": 1.0, "m2-logit": 1.0, "m3-form": 1.0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=Path("data/snapshot"))
    parser.add_argument("--db", type=Path, default=Path("data/training/f1-training.sqlite"))
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument(
        "--revision", default="baseline-v0.1.0",
        help="stable model revision; change this when changing features or weights",
    )
    options = parser.parse_args(argv)
    dataset = load_snapshot(options.data_dir)
    result = run_backtest(
        dataset, target_season=options.season, weights=DEFAULT_WEIGHTS
    )
    if not result.rounds:
        parser.error(
            "no races to score in selected season; refresh the dataset or "
            "select a season with completed results"
        )
    with TrainingStore(options.db) as store:
        store.import_dataset(dataset)
        store.record_backtest(dataset, result, options.revision)
        inventory = store.inventory()
    metrics = {
        model: metric.model_dump(mode="json")
        for model, metric in aggregate_rounds(result.rounds).items()
    }
    print(json.dumps(
        {
            "dataset_id": dataset.dataset_id,
            "dataset_digest": dataset.dataset_sha256,
            "season": result.target_season,
            "model_revision": options.revision,
            "scored_rounds": len(result.rounds),
            "skipped_rounds": len(result.skipped),
            "metrics": metrics,
            "inventory": inventory,
            "training_db": str(options.db),
        },
        indent=2, sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
