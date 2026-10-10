"""Build a local F1 training store from verified snapshots, offline."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "engine") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "engine"))

from f1engine.backtest import aggregate_rounds, run_backtest
from f1engine.ingestion import load_snapshot
from f1engine.training_store import TrainingStore, build_training_store

DEFAULT_WEIGHTS = {"m1-gbm": 1.0, "m2-logit": 1.0, "m3-form": 1.0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot", action="append",
        help="Verified parquet snapshot directory; repeat for disjoint seasons",
    )
    parser.add_argument("--as-of", help="Exclusive YYYY-MM-DD outcome cutoff")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--data-dir", type=Path, default=Path("data/snapshot"))
    parser.add_argument("--db", type=Path, default=Path("data/training/f1-training.sqlite"))
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument(
        "--revision", default="baseline-v0.1.0",
        help="stable model revision; change this when changing features or weights",
    )
    options = parser.parse_args(argv)

    if options.snapshot is not None:
        if not options.as_of:
            parser.error("--as-of is required with --snapshot")
        output = options.output or options.db
        counts = build_training_store(
            [Path(path) for path in options.snapshot], output,
            as_of=date.fromisoformat(options.as_of),
        )
        print(f"training store: {output} — {counts}")
        return 0

    if options.as_of is not None or options.output is not None:
        parser.error("--as-of and --output require at least one --snapshot")

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
