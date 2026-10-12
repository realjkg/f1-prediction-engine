#!/usr/bin/env python3
"""Launch the single-image F1 demo on an application host.

Public self-hosted deployment: specify F1E_DEMO_TLS_CERT and
F1E_DEMO_TLS_KEY, enforcing TLS 1.3. Vercel's managed edge terminates HTTPS
before the HTTP server in the OCI Function; that edge's TLS policy must be
qualified separately (Vercel currently also supports TLS 1.2).
"""

from __future__ import annotations

import os
import ssl
import sys
from pathlib import Path

import uvicorn


def configured_server() -> uvicorn.Config:
    port = int(os.environ.get("PORT", "8080"))
    if not 1 <= port <= 65535:
        raise ValueError("invalid demo serving port")
    cert = os.environ.get("F1E_DEMO_TLS_CERT")
    key = os.environ.get("F1E_DEMO_TLS_KEY")
    if bool(cert) != bool(key):
        raise RuntimeError("both TLS certificate and private key are required")
    managed_edge = os.environ.get("VERCEL") == "1"
    localhost_test = os.environ.get("F1E_DEMO_LOOPBACK_ONLY") == "1"
    if not cert and not managed_edge and not localhost_test:
        raise RuntimeError(
            "TLS 1.3 required for independent hosting; "
            "plaintext permitted only behind Vercel's managed edge "
            "or when explicitly confined to local demo loopback"
        )
    if localhost_test and managed_edge:
        raise RuntimeError("loopback test flag is not allowed on Vercel")
    kwargs: dict[str, object] = {
        "factory": True,
        "host": "127.0.0.1" if localhost_test else "0.0.0.0",
        "port": port,
        "workers": 1,
    }
    if cert:
        if not ssl.HAS_TLSv1_3:
            raise RuntimeError("TLS 1.3 unavailable in OpenSSL")
        for path in (cert, key):
            if not Path(path).is_file():
                raise RuntimeError("configured TLS file missing")
        kwargs["ssl_certfile"] = cert
        kwargs["ssl_keyfile"] = key
    config = uvicorn.Config("f1engine.demo_site:create_unified_demo", **kwargs)
    if cert:
        config.load()
        if config.ssl is None:
            raise RuntimeError("server TLS context not created")
        config.ssl.minimum_version = ssl.TLSVersion.TLSv1_3
    return config


if __name__ == "__main__":
    try:
        options = configured_server()
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Unified demo startup refused: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    uvicorn.Server(options).run()
