#!/usr/bin/env python3
"""Verify an F1 Pit Wall public container endpoint without operator credentials.

Use after Vercel deploy to check the actual network path, not just the image.
Never pass secret tokens to this smoke test. A successful TLS 1.3 connection
proves support, not that Vercel rejects TLS 1.2 browser clients.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def request(origin: str, path: str, *, method: str = "GET", data: bytes | None = None):
    req = Request(
        origin + path, method=method, data=data,
        headers={"Accept": "application/json", **({"Content-Type": "application/json"} if data is not None else {})},
    )
    try:
        with urlopen(req, timeout=20) as response:
            return response.status, dict(response.headers), response.read(1_000_001)
    except HTTPError as error:
        return error.code, dict(error.headers), error.read(1_000_001)


def verify_tls13(host: str, port: int) -> None:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    with socket.create_connection((host, port), timeout=15) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as connection:
            assert connection.version() == "TLSv1.3", "TLS 1.3 negotiation failed"


def verify(origin: str, *, local: bool = False) -> None:
    parsed = urlsplit(origin)
    assert parsed.hostname, "endpoint hostname required"
    assert not parsed.username and not parsed.password, "credentials in URL prohibited"
    assert not parsed.query and not parsed.fragment and parsed.path in ("", "/"), (
        "provide the endpoint origin only, without path/query/fragment"
    )
    if local:
        assert parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1"), (
            "local smoke only accepts HTTP on loopback"
        )
    else:
        assert parsed.scheme == "https", "public endpoints must use HTTPS"
        verify_tls13(parsed.hostname, parsed.port or 443)

    origin = origin.rstrip("/")
    status, headers, body = request(origin, "/")
    assert status == 200 and b'id="root"' in body, "UI missing"
    assert headers.get("X-Content-Type-Options", headers.get("x-content-type-options")) == "nosniff"
    assert headers.get("X-Frame-Options", headers.get("x-frame-options")) == "DENY"
    assert "no-store" in headers.get("Cache-Control", headers.get("cache-control", ""))
    if not local:
        assert "max-age=" in headers.get(
            "Strict-Transport-Security", headers.get("strict-transport-security", "")
        ), "HSTS missing"

    for path in ("/healthz", "/api/config", "/api/races", "/api/evidence", "/api/supply-chain"):
        status, _, raw = request(origin, path)
        assert status == 200, f"{path} expected 200, got {status}"
        obj = json.loads(raw)
        if path == "/healthz":
            assert obj["status"] == "ok"
        elif path == "/api/config":
            assert obj["advisoryOnly"] is True and obj["briefMode"] == "fixture"
        elif path == "/api/races":
            assert obj["total"] > 0
        elif path == "/api/evidence":
            assert obj["chainValid"] is True and obj["total"] > 0
        elif path == "/api/supply-chain":
            assert obj["releaseReady"] is False and obj["totalComponents"] > 0

    for path in ("/metrics", "/docs", "/redoc", "/openapi.json"):
        status, _, _ = request(origin, path)
        assert status == 404, f"private diagnostics exposed at {path}: {status}"

    status, _, _ = request(
        origin, "/api/claude/brief", method="POST",
        data=json.dumps({"raceId": "australian", "season": 2024}).encode(),
    )
    assert status in (403, 503), f"unauthenticated Claude access not denied: {status}"
    print("PASS: public UI/API, evidence, partial SBOM, protected Claude, and transport checks")
    if not local:
        print("PASS: CA/hostname-verified TLS 1.3 negotiated (does not imply TLS-1.2-only clients are blocked)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="https://actual-deployment-hostname")
    parser.add_argument(
        "--local-loopback", action="store_true",
        help="permit http://127.0.0.1:port only for a local container smoke",
    )
    args = parser.parse_args()
    verify(args.origin, local=args.local_loopback)


if __name__ == "__main__":
    main()
