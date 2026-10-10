#!/usr/bin/env python3
"""One-command demo: verify → predict → prove → narrate → serve.

Spec ("One command, identical every time"): `make demo` verifies the pinned
snapshot's integrity before anything is predicted, trains and predicts the
2024 rounds through the ensemble, scores them against actual results, writes
every record into the sha256-chained evidence ledger, narrates the fixture
race brief, and serves the API. Two runs from the same snapshot produce
byte-identical ledgers — the stored records contain no wall-clock time: the
generation timestamp is the dataset's pinned provenance timestamp, and
durations are in-memory telemetry that never enters evidence.

Typed failures stay typed end to end: a mismatched snapshot refuses the run
through the ingestion layer's own typed errors (DATA_SNAPSHOT_MISMATCH
family), and a missing brief implementation degrades the advisory narrate
stage with a printed note — never a silent fallback.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn
from f1engine.app import APP_TITLE, APP_VERSION, create_app
from f1engine.backtest import (
    METRIC_DEFINITIONS,
    BacktestResult,
    aggregate_rounds,
    run_backtest,
)
from f1engine.brief import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    BriefConfig,
    BriefError,
    brief_config_from_env,
    generate_brief,
)
from f1engine.evidence import (
    PredictionRecord,
    append_record,
    build_backtest_record,
    build_prediction_record,
    verify_chain,
)
from f1engine.ingestion import PinnedDataset, load_snapshot
from f1engine.observability import (
    EventStatus,
    Signal,
    clear_events,
    emit,
    observe_prediction_duration,
)

DEFAULT_PORT = 8000
TARGET_SEASON = 2024
WEIGHTS: dict[str, float] = {"m1-gbm": 1.0, "m2-logit": 1.0, "m3-form": 1.0}
EVIDENCE_BASIS = "REAL MODELS — PINNED DATASET 2020–2024 — NO LIVE INFERENCE"


def _log(stage: str, message: str) -> None:
    print(f"[demo:{stage}] {message}", flush=True)


def predict_and_prove(
    dataset: PinnedDataset, ledger_path: Path, season: int
) -> BacktestResult:
    """Run the expanding window and append evidence for it.

    Writes one prediction record per scoreable round, then the backtest
    record. Both stages consume the same run — the predictions in the ledger
    are exactly the ones the backtest scored, so the evidence and the
    accuracy claim cannot drift apart.
    """
    result = run_backtest(dataset, target_season=season, weights=WEIGHTS)

    round_by_id = {race.race_id: race for race in dataset.races}
    for backtest_round in result.rounds:
        for prediction in backtest_round.predictions:
            duration_ms = backtest_round.model_duration_ms.get(prediction.model_id)
            if duration_ms is not None:
                observe_prediction_duration(prediction.model_id, duration_ms / 1000.0)
        record = build_prediction_record(
            backtest_round.predictions,
            backtest_round.verdict,
            dataset,
            round_by_id[backtest_round.race_id],
            EVIDENCE_BASIS,
        )
        append_record(ledger_path, record)
        emit(
            Signal.EVIDENCE_LIFECYCLE,
            EventStatus.OK,
            {"record": record.prediction_id, "type": "prediction"},
        )

    backtest_record = build_backtest_record(
        dataset,
        season=season,
        first_round=result.rounds[0].round_number,
        last_round=result.rounds[-1].round_number,
        metrics=aggregate_rounds(result.rounds),
        metric_definitions=METRIC_DEFINITIONS,
        skipped_rounds=result.skipped,
        evidence_basis=EVIDENCE_BASIS,
    )
    append_record(ledger_path, backtest_record)
    emit(
        Signal.EVIDENCE_LIFECYCLE,
        EventStatus.OK,
        {"record": backtest_record.backtest_id, "type": "backtest"},
    )
    return result


def narrate(records: list[PredictionRecord]) -> None:
    """Race briefs for the committed records. Advisory, outside the evidence chain.

    Mode follows the environment (OLLAMA_BASE_URL set -> live digest-pinned
    Ollama at temperature 0; unset -> deterministic fixture). A live failure
    (absent Ollama, timeout, unpinned model, invalid response) degrades that
    record to the fixture brief under its banner — typed, logged, never a
    silent fallback.
    """
    config = brief_config_from_env()
    degraded = 0
    for record in records:
        try:
            brief = generate_brief(record, config=config)
        except BriefError as error:
            # Fixture briefs are pure functions of the record — if one of
            # THOSE fails, the exception propagates; only live mode degrades.
            brief = generate_brief(record, config=_fixture_config())
            degraded += 1
            emit(
                Signal.BRIEF_GENERATION,
                EventStatus.DEGRADED,
                {"raceId": record.race.race_id, "reason": type(error).__name__},
            )
        emit(
            Signal.BRIEF_GENERATION,
            EventStatus.OK,
            {"raceId": record.race.race_id, "mode": brief.mode},
        )
        _log(
            "narrate",
            f"{brief.evidence_basis} — {record.prediction_id}: {brief.content.headline}",
        )
    if degraded:
        _log("narrate", f"{degraded} record(s) degraded to the fixture brief")


def _committed_predictions(ledger_path: Path) -> list[PredictionRecord]:
    """Read back the prediction records just appended — the committed forms.

    Briefs narrate what is IN the ledger (each with its chain hash), not any
    in-memory build; a record that fails to validate here is a real defect.
    """
    records: list[PredictionRecord] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if payload.get("recordType") == "prediction":
            records.append(PredictionRecord.model_validate_json(line))
    return records


def _fixture_config() -> BriefConfig:
    """The deterministic fixture config — no network, no model call."""
    return BriefConfig(
        mode="fixture",
        ollama_base_url=None,
        ollama_model=DEFAULT_OLLAMA_MODEL,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )


def verify(data_dir: Path) -> PinnedDataset:
    """Load and hash-verify the pinned snapshot; typed refusal on mismatch."""
    _log("verify", f"re-hashing {data_dir} against provenance.json")
    dataset = load_snapshot(data_dir)
    emit(
        Signal.DATA_INGEST,
        EventStatus.OK,
        {"dataset": dataset.dataset_id, "sha256": dataset.dataset_sha256[:16]},
    )
    _log("verify", f"pinned dataset {dataset.dataset_id} verified ({len(dataset.races)} races)")
    return dataset


def serve(port: int, host: str) -> None:
    """Serve the engine API until interrupted, behind the evidence banner."""
    banner = f"{APP_TITLE} v{APP_VERSION} — {EVIDENCE_BASIS}"
    print(f"[demo:serve] {banner}", flush=True)
    print(
        f"[demo:serve] listening on http://{host}:{port} (docs at /docs, metrics at /metrics)",
        flush=True,
    )
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


def run_demo(
    data_dir: Path, ledger_path: Path, season: int, brief: bool
) -> BacktestResult:
    """The demo pipeline without the server: verify → predict → prove → narrate.

    Determinism contract: every stored record derives from the pinned dataset
    and fixed seeds only — two calls with the same inputs append identical
    bytes (tested by test_demo.py, run twice in-process).
    """
    clear_events()
    if ledger_path.exists():
        # The demo regenerates its evidence: run N's ledger is a pure
        # function of the snapshot, so a re-run reproduces the same bytes
        # rather than accreting a second chain (determinism gate).
        ledger_path.unlink()
    # The served API reads this same path (DEFAULT_LEDGER_PATH) — create the
    # parent so the first run's appends land where the demo will serve from.
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    dataset = verify(data_dir)
    _log("predict", f"expanding-window predictions for {season}, per-model + ensemble, into the ledger")
    result = predict_and_prove(dataset, ledger_path, season)
    metrics = aggregate_rounds(result.rounds)
    scored = ", ".join(f"{key}={value.winner_hit_rate:.2f}" for key, value in metrics.items())
    _log("prove", f"backtest: {len(result.rounds)} rounds scored — winner hit rate {scored}")
    if brief:
        narrate(_committed_predictions(ledger_path))
    verify_chain(ledger_path)
    _log("prove", f"ledger at {ledger_path} — chain verified, {len(result.rounds) + 1} records appended")
    emit(
        Signal.BACKTEST_ACCURACY,
        EventStatus.OK,
        {"rounds": len(result.rounds), "season": season},
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the F1 prediction demo pipeline.")
    parser.add_argument("--data-dir", type=Path, default=Path("data/snapshot"))
    parser.add_argument("--ledger", type=Path, default=Path("data/evidence/ledger.jsonl"))
    parser.add_argument("--season", type=int, default=TARGET_SEASON)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--no-serve",
        action="store_true",
        help="run verify→prove→narrate and exit (CI, determinism gate)",
    )
    parser.add_argument("--no-brief", action="store_true", help="skip the narrate stage")
    args = parser.parse_args(argv)

    run_demo(args.data_dir, args.ledger, args.season, brief=not args.no_brief)
    if not args.no_serve:
        serve(args.port, args.host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
