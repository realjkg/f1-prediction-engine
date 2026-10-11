"""Authenticated OpenF1 MQTT capture with a bounded, source-preserving spool.

Optional dependency: paho-mqtt (not imported during API serving or tests).
This captures raw topic events; a separate time-aligned and verified projection
must produce per-lap checkpoints. No outcome labels or forecast are inferred.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

TOPICS = (
    "v1/position", "v1/intervals", "v1/laps", "v1/pit",
    "v1/stints", "v1/race_control", "v1/weather",
)
BROKER = "mqtt.openf1.org"
PORT = 8883
MAX_MESSAGE_BYTES = 512_000


def normalize_message(
    topic: str, payload: bytes, session_key: int, captured_at: datetime,
) -> dict[str, object] | None:
    """Keep provider _id/_key and exact bytes; reject other sessions and times."""
    if topic not in TOPICS:
        raise ValueError("unauthorized OpenF1 topic")
    if not (0 < len(payload) <= MAX_MESSAGE_BYTES):
        raise ValueError("invalid MQTT payload size")
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("capture clock must be timezone aware")
    try:
        text = payload.decode("utf-8")
        message = json.loads(text)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid UTF-8 JSON MQTT payload") from exc
    if not isinstance(message, dict):
        raise ValueError("OpenF1 topic payload must be a JSON object")
    if message.get("session_key") != session_key:
        return None
    provider_id = message.get("_id")
    provider_key = message.get("_key")
    if not isinstance(provider_id, int) or isinstance(provider_id, bool):
        raise ValueError("missing provider sequence _id")
    if not isinstance(provider_key, str) or not provider_key:
        raise ValueError("missing provider document _key")
    event_time = message.get("date")
    if event_time is not None:
        if not isinstance(event_time, str):
            raise ValueError("invalid provider event time")
        try:
            timestamp = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid provider event time") from exc
        if timestamp.tzinfo is None:
            raise ValueError("provider event timestamp has no timezone")
        if timestamp > captured_at:
            raise ValueError("provider event time follows capture clock")
    return {
        "provider": "openf1",
        "topic": topic,
        "sessionKey": session_key,
        "providerSequence": provider_id,
        "providerKey": provider_key,
        "providerDate": event_time,
        "capturedAt": captured_at.astimezone(UTC).isoformat(),
        "rawPayloadSha256": hashlib.sha256(payload).hexdigest(),
        "rawPayloadText": text,
    }


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
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
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
