#!/usr/bin/env python3
"""Turn one captured OpenF1 MQTT spool into a replayable as-of source bundle.

This is offline and uses no provider credentials. Never treat all provider
events as equally available; filter by RECEIVE time, not just event time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

MAX_LINES = 120_000
TOPICS = frozenset((
    "position", "intervals", "laps", "pit", "stints", "race_control", "weather",
))


def parse_time(text: str) -> datetime:
    date = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("capture and cutoff require timezone")
    return date.astimezone(UTC)


def spool_to_bundle(
    lines: list[str], *, session_key: int, cutoff: datetime,
) -> dict[str, object]:
    if cutoff.tzinfo is None:
        raise ValueError("cutoff requires timezone")
    if len(lines) > MAX_LINES:
        raise ValueError("source spool exceeds event budget")
    events: dict[str, list[dict[str, object]]] = {topic: [] for topic in TOPICS}
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            raise ValueError(f"blank source spool line {index}")
        try:
            packet = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"unparseable source spool line {index}") from exc
        if not isinstance(packet, dict) or packet.get("provider") != "openf1":
            raise ValueError("unrecognized provider")
        topic = packet.get("topic")
        if not isinstance(topic, str) or not topic.startswith("v1/"):
            raise ValueError("invalid provider topic")
        group = topic.removeprefix("v1/")
        if group not in TOPICS:
            raise ValueError("topic not permitted by lap collector")
        if packet.get("sessionKey") != session_key:
            continue
        received = parse_time(packet.get("capturedAt", ""))
        if received > cutoff.astimezone(UTC):
            continue
        raw = packet.get("rawPayloadText")
        if not isinstance(raw, str):
            raise ValueError("source message bytes missing")
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if digest != packet.get("rawPayloadSha256"):
            raise ValueError("captured source payload hash mismatch")
        original = json.loads(raw)
        if not isinstance(original, dict) or original.get("session_key") != session_key:
            raise ValueError("provider message session mismatch")
        if (
            original.get("_id") != packet.get("providerSequence")
            or original.get("_key") != packet.get("providerKey")
        ):
            raise ValueError("provider document identity mismatch")
        events[group].append(packet)
    return {"session_key": session_key, "events": events}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spool", type=Path, required=True)
    parser.add_argument("--session-key", type=int, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = spool_to_bundle(
        args.spool.read_text(encoding="utf-8").splitlines(),
        session_key=args.session_key, cutoff=parse_time(args.as_of),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n"
    with args.output.open("x", encoding="utf-8") as output:
        output.write(payload)
    print(json.dumps({
        "sessionKey": args.session_key,
        "bundleSha256": hashlib.sha256(payload.encode()).hexdigest(),
        "eventsByTopic": {topic: len(rows) for topic, rows in bundle["events"].items()},
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
