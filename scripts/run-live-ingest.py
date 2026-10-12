#!/usr/bin/env python3
"""Run the live OpenF1 ingest: authenticated MQTT/TLS 1.3 in, per-lap artifacts out.

Optional dependency: paho-mqtt, in a separate collector environment. The
private engine API serves what this writes (read-only), so point
F1E_LAP_TRACE_PATH and F1E_INRACE_ARTIFACT_DIR at --trace and --artifacts.

Credentials are backend-only environment variables:
  OPENF1_USER + OPENF1_PASSWORD   exchanged for a one-hour token, refreshed
                                  automatically before it expires
  OPENF1_ACCESS_TOKEN             a static token instead (the run ends when it
                                  expires; pair with OPENF1_USER as the login)

No prediction is promoted. Fusion uses the frozen prior and weight you supply.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from f1engine.live_ingest import LiveIngestor
from f1engine.live_prior import PreRacePrior
from f1engine.openf1_feed import (
    BROKER,
    PORT,
    TOKEN_REFRESH_MARGIN_SECONDS,
    TOPICS,
    build_tls_context,
    fetch_access_token,
)


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    cli.add_argument("--session-key", type=int, required=True)
    cli.add_argument("--season", type=int, required=True)
    cli.add_argument("--race-id", required=True)
    cli.add_argument("--total-laps", type=int, required=True)
    cli.add_argument("--entrants", required=True, help="comma-separated verified driver numbers")
    cli.add_argument("--trace", type=Path, required=True)
    cli.add_argument("--artifacts", type=Path, required=True)
    cli.add_argument("--spool", type=Path, required=True)
    cli.add_argument("--rights-reference", required=True)
    cli.add_argument("--prior", type=Path, help="frozen race-matched pre-race prior (JSON)")
    cli.add_argument("--scenario-weight", type=float, default=0.5)
    cli.add_argument("--trials", type=int, default=2000)
    cli.add_argument("--max-runtime-seconds", type=int, default=4 * 3600)
    args = cli.parse_args(argv)

    user = os.environ.get("OPENF1_USER", "")
    password = os.environ.get("OPENF1_PASSWORD", "")
    static_token = os.environ.get("OPENF1_ACCESS_TOKEN", "")
    if not user or not (password or static_token):
        cli.error("set OPENF1_USER and OPENF1_PASSWORD (or OPENF1_ACCESS_TOKEN) in the backend environment")
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        cli.error("install vetted paho-mqtt in a separate collector environment")

    prior = None
    if args.prior is not None:
        prior = PreRacePrior.model_validate_json(args.prior.read_text(encoding="utf-8"))
    entrants = tuple(int(part.strip()) for part in args.entrants.split(","))
    ingestor = LiveIngestor(
        session_key=args.session_key, season=args.season, race_id=args.race_id,
        total_laps=args.total_laps, entrants=entrants, trace_path=args.trace,
        artifact_root=args.artifacts, spool_path=args.spool,
        rights_evidence=args.rights_reference, prior=prior,
        scenario_weight=args.scenario_weight, trials=args.trials,
    )

    def obtain_token() -> tuple[str, float]:
        if password:
            token, lifetime = fetch_access_token(user, password)
            return token, time.monotonic() + lifetime - TOKEN_REFRESH_MARGIN_SECONDS
        return static_token, float("inf")

    token, refresh_at = obtain_token()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    client.username_pw_set(username=user, password=token)
    # Native MQTT over TLS only: CA chain and hostname verified, TLS 1.3 minimum,
    # no downgrade and no insecure mode.
    client.tls_set_context(build_tls_context())
    client.tls_insecure_set(False)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            emit("connection_rejected", reason=str(reason_code))
            return
        for topic in TOPICS:
            _client.subscribe(topic, qos=0)
        emit("subscribed", topics=list(TOPICS), sessionKey=args.session_key)

    def on_message(_client, _userdata, message):
        emission = ingestor.handle(message.topic, message.payload, datetime.now(UTC))
        if emission is not None:
            emit(
                "lap_checkpoint", lap=emission.lap, scenarioStatus=emission.scenario_status,
                fused=emission.fused, checkpointSha256=emission.checkpoint_sha256,
            )
        if ingestor.finished:
            emit("race_distance_reached", totalLaps=args.total_laps)
            stop.set()

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_start()
    emit("started", sessionKey=args.session_key, raceId=args.race_id, modelPromoted=False)
    deadline = time.monotonic() + args.max_runtime_seconds
    try:
        while not stop.wait(timeout=15):
            if time.monotonic() >= deadline:
                emit("max_runtime_reached")
                break
            if time.monotonic() >= refresh_at:
                if not password:
                    emit("static_token_expired")
                    break
                try:
                    token, refresh_at = obtain_token()
                except ValueError as exc:
                    emit("token_refresh_failed", reason=str(exc))
                    break
                client.username_pw_set(username=user, password=token)
                client.reconnect()
                emit("token_refreshed")
    finally:
        client.disconnect()
        client.loop_stop()
        stats = ingestor.stats
        emit(
            "stopped", received=stats.received, duplicates=stats.duplicates,
            rejected=stats.rejected, refusals=stats.refusals,
            lastRefusal=stats.last_refusal, lastRejection=stats.last_rejection,
            lastLap=ingestor.last_lap,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
