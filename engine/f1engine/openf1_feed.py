"""OpenF1 MQTT feed primitives shared by the offline collector and live ingest.

Standard library only, so the optional collector environment never needs the
engine's scientific stack. Nothing here opens a network connection except
`fetch_access_token`, which talks to OpenF1's token endpoint over verified TLS.
"""

from __future__ import annotations

import hashlib
import json
import ssl
import urllib.parse
import urllib.request
from datetime import UTC, datetime

TOPICS = (
    "v1/position", "v1/intervals", "v1/laps", "v1/pit",
    "v1/stints", "v1/race_control", "v1/weather",
)
BROKER = "mqtt.openf1.org"
PORT = 8883
MAX_MESSAGE_BYTES = 512_000


def build_tls_context() -> ssl.SSLContext:
    """Require authenticated TLS 1.3+; never negotiate an older protocol.

    If Python/OpenSSL lacks TLS 1.3 support, refuse collection rather than
    weakening certificate validation or silently falling back to TLS 1.2.
    """
    if not ssl.HAS_TLSv1_3:
        raise RuntimeError("TLS 1.3 is required; collector OpenSSL lacks support")
    context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


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


TOKEN_URL = "https://api.openf1.org/token"
MAX_TOKEN_RESPONSE_BYTES = 16_384
# OpenF1 documents one-hour tokens; refresh well before expiry.
TOKEN_REFRESH_MARGIN_SECONDS = 600


def fetch_access_token(
    username: str, password: str, *, timeout: float = 15.0,
) -> tuple[str, int]:
    """Exchange backend-only credentials for a bearer token and its lifetime.

    Verified HTTPS with the default context; the token is returned to the
    caller and never logged. Raises ValueError on any malformed response.
    """
    if not username or not password:
        raise ValueError("OpenF1 username and password are required")
    body = urllib.parse.urlencode({"username": username, "password": password}).encode()
    request = urllib.request.Request(
        TOKEN_URL, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    # The token endpoint is part of the same protected telemetry boundary.
    # Enforce TLS 1.3+ and verified hostname/CA, just like the MQTT channel;
    # a TLS 1.2-only endpoint is a hard failure, never a downgrade.
    context = build_tls_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as reply:
            raw = reply.read(MAX_TOKEN_RESPONSE_BYTES + 1)
    except OSError as exc:
        raise ValueError("OpenF1 token request failed") from exc
    if len(raw) > MAX_TOKEN_RESPONSE_BYTES:
        raise ValueError("OpenF1 token response too large")
    try:
        data = json.loads(raw)
        access = data["access_token"]
        lifetime = int(data["expires_in"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("OpenF1 token response malformed") from exc
    if not isinstance(access, str) or not access or lifetime < 60:
        raise ValueError("OpenF1 token response malformed")
    return access, lifetime
