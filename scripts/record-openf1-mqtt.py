"""Authenticated OpenF1 MQTT capture with a bounded, source-preserving spool.

Optional dependency: paho-mqtt (not imported during API serving or tests).
This captures raw topic events; a separate time-aligned and verified projection
must produce per-lap checkpoints. No outcome labels or forecast are inferred.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from f1engine.openf1_feed import (  # noqa: F401  (re-exported for tests and callers)
    BROKER,
    MAX_MESSAGE_BYTES,
    PORT,
    TOPICS,
    build_tls_context,
    normalize_message,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-key", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-messages", type=int, default=10000)
    parser.add_argument("--rights-reference", required=True)
    args = parser.parse_args(argv)
    if args.session_key < 1 or args.max_messages < 1:
        parser.error("session key and max-messages must be positive")
    if not args.rights_reference.strip():
        parser.error("licensed streaming must have a recorded rights reference")
    user = os.environ.get("OPENF1_USER")
    token = os.environ.get("OPENF1_ACCESS_TOKEN")
    if not user or not token:
        parser.error("OPENF1_USER and OPENF1_ACCESS_TOKEN are required in backend environment")
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        parser.error("install vetted paho-mqtt in a separate collector environment")
        raise RuntimeError("unreachable") from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    done = threading.Event()
    received = 0
    with args.output.open("a", encoding="utf-8") as out:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        client.username_pw_set(username=user, password=token)
        # Native MQTT over TLS only: validate CA chain + broker hostname.
        # TLS 1.3 is mandatory; failed negotiation is a hard error.
        client.tls_set_context(build_tls_context())
        client.tls_insecure_set(False)
        client.reconnect_delay_set(min_delay=1, max_delay=30)

        def on_connect(_client, _userdata, _flags, reason_code, _properties):
            if reason_code != 0:
                print("OpenF1 authentication or connection rejected", file=sys.stderr)
                done.set()
                return
            for topic in TOPICS:
                _client.subscribe(topic, qos=0)

        def on_message(_client, _userdata, message):
            nonlocal received
            if done.is_set():
                return
            try:
                event = normalize_message(
                    message.topic, message.payload, args.session_key, datetime.now(UTC)
                )
            except ValueError as exc:
                print(f"Invalid source event: {exc}", file=sys.stderr)
                done.set()
                return
            if event is None:
                return
            out.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
            out.flush()
            os.fsync(out.fileno())
            received += 1
            if received >= args.max_messages:
                done.set()

        client.on_connect = on_connect
        client.on_message = on_message
        try:
            client.connect(BROKER, PORT, keepalive=60)
            client.loop_start()
            print(
                f"Recording authorized OpenF1 MQTT session {args.session_key}"
                f" to {args.output}; bounded to {args.max_messages} events"
            )
            done.wait(timeout=3300)  # refresh hour-lived OAuth token between sessions
        finally:
            client.disconnect()
            client.loop_stop()
    print(f"Recorded {received} source events; no live race prediction has run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
