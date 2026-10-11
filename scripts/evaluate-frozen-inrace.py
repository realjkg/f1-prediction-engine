#!/usr/bin/env python3
"""Score source-bound historical lap replays without fitting on target outcomes.

Manifest entries identify retained trace/artifact files and normalized
published classification files. A classification's content hash is verified
before reading its winner; operator must separately review the provenance,
license and historical provider publication timing of that normalization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from f1engine.inrace_evaluation import FrozenEvaluationCase  # noqa: E402
from f1engine.inrace_pipeline import (  # noqa: E402
    read_fusion_artifacts,
    read_run_artifact,
)
from f1engine.inrace_walkforward import (  # noqa: E402
    evaluate_forward_weights,
    write_forward_report,
)
from f1engine.lap_trace import verify_lap_trace  # noqa: E402


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("result publication time must be timezone-aware")
    return parsed


def cases_from_manifest(path: Path) -> list[FrozenEvaluationCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"entries"}:
        raise ValueError("manifest must contain only an entries array")
    if not isinstance(data["entries"], list) or len(data["entries"]) > 1000:
        raise ValueError("invalid number of historical race entries")
    results = []
    for item in data["entries"]:
        if not isinstance(item, dict) or set(item) != {
            "season", "raceId", "lap", "tracePath", "artifactRoot",
            "resultSourcePath", "resultSourceSha256",
        }:
            raise ValueError("historical evaluation entry schema invalid")
        season, race_id, lap = item["season"], item["raceId"], item["lap"]
        trace = verify_lap_trace(Path(item["tracePath"]))
        checkpoints = [
            record for record in trace
            if (record.checkpoint.season, record.checkpoint.race_id, record.checkpoint.lap)
            == (season, race_id, lap)
        ]
        if len(checkpoints) != 1:
            raise ValueError("expected one verified historical checkpoint per race")
        record = checkpoints[0]
        artifact_root = Path(item["artifactRoot"])
        artifact = read_run_artifact(
            artifact_root, season=season, race_id=race_id, lap=lap,
            checkpoint_sha256=record.record_sha256,
        )
        if artifact is None or artifact.scenario is None:
            raise ValueError("no matching intact conditional scenario to compare")
        fusion = read_fusion_artifacts(artifact_root, record, artifact)
        if fusion is None:
            raise ValueError("no frozen pre-race prior/combined scenario evidence")
        content = Path(item["resultSourcePath"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != item["resultSourceSha256"]:
            raise ValueError("result source content does not match retained digest")
        outcome = json.loads(content)
        if not isinstance(outcome, dict) or set(outcome) != {
            "season", "raceId", "winnerDriverNumber", "publishedAt",
        }:
            raise ValueError("normalized result source schema invalid")
        if (outcome["season"], outcome["raceId"]) != (season, race_id):
            raise ValueError("classification belongs to another race")
        results.append(FrozenEvaluationCase(
            season=season, race_id=race_id, lap=lap,
            observed_at=record.checkpoint.observed_at,
            result_published_at=_time(outcome["publishedAt"]),
            winner_driver_number=outcome["winnerDriverNumber"],
            initial_prior={
                d.driver_number: d.pre_race_probability for d in fusion.candidates
            },
            scenario=artifact.scenario, combined=fusion,
        ))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_forward_weights(cases_from_manifest(args.manifest))
    write_forward_report(args.output, report)
    print(json.dumps({
        "reportSha256": report.report_sha256,
        "scoredRaces": report.scored_races,
        "unscoredRaces": report.unscored_races,
        "modelPromotionAllowed": False,
        "pairedSummary": report.paired_summary,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
