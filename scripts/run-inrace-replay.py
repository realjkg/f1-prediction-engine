#!/usr/bin/env python3
"""Execute a frozen lap replay, retain provenance, and optionally blend prior.

No provider network access or classified result in this path. A signed and
source-verified pre-race forecast must be prepared independently; the prior
file is only a transport container and its claims require external review.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from f1engine.inrace_pipeline import project_and_record, write_fusion_artifacts  # noqa: E402
from f1engine.live_prior import PreRacePrior  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--source", type=Path, required=True)
    cli.add_argument("--trace", type=Path, required=True)
    cli.add_argument("--artifacts", type=Path, required=True)
    cli.add_argument("--race-id", required=True)
    cli.add_argument("--season", type=int, required=True)
    cli.add_argument("--session-key", type=int, required=True)
    cli.add_argument("--lap", type=int, required=True)
    cli.add_argument("--total-laps", type=int, required=True)
    cli.add_argument("--as-of", required=True, help="timezone-aware ISO cutoff")
    cli.add_argument("--captured-at", required=True)
    cli.add_argument("--entrants", required=True, help="comma-separated verified driver numbers")
    cli.add_argument("--source-type", choices=[
        "historical-archive", "licensed-live", "synthetic-fixture",
    ], required=True)
    cli.add_argument("--rights-reference")
    cli.add_argument("--prior", type=Path, help="optional frozen race-matched prior")
    cli.add_argument("--scenario-weight", type=float, default=0.5)
    cli.add_argument("--trials", type=int, default=2000)
    args = cli.parse_args(argv)
    entrants = tuple(int(v.strip()) for v in args.entrants.split(","))
    observed = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    captured = datetime.fromisoformat(args.captured_at.replace("Z", "+00:00"))
    record, artifact = project_and_record(
        args.source.read_bytes(), trace_path=args.trace,
        artifact_root=args.artifacts, season=args.season,
        race_id=args.race_id, session_key=args.session_key,
        lap=args.lap, total_laps=args.total_laps, cutoff=observed,
        captured_at=captured, entrant_numbers=entrants,
        source_type=args.source_type, rights_evidence=args.rights_reference,
        trials=args.trials,
    )
    report: dict[str, object] = {
        "race": args.race_id, "lap": args.lap, "totalLaps": args.total_laps,
        "observationHash": record.record_sha256,
        "scenarioStatus": artifact.status,
        "artifactHash": artifact.artifact_sha256,
        "sourceType": args.source_type,
        "modelPromoted": False,
    }
    if args.prior is not None:
        if artifact.scenario is None:
            report["priorFusion"] = "refused: conditional scenario unavailable"
        else:
            prior = PreRacePrior.model_validate_json(args.prior.read_text(encoding="utf-8"))
            fusion = write_fusion_artifacts(
                args.artifacts, record, artifact, prior,
                scenario_weight=args.scenario_weight,
            )
            report["priorFusion"] = "unqualified-research"
            report["fusionHash"] = fusion.output_sha256
            report["priorModelRevision"] = fusion.model_revision
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
