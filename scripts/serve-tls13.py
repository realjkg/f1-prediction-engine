#!/usr/bin/env python3
"""TLS 1.3-only, mutual-TLS FastAPI server for secure Compose.

Uvicorn CLI certificate switches alone do not set an explicit minimum
TLS version. Configure OpenSSL's server SSLContext directly and refuse
startup if TLS 1.3 or the required certificate material is missing.
"""

from __future__ import annotations

import os
import ssl
import sys
from pathlib import Path

import uvicorn


def secure_config() -> uvicorn.Config:
    if not ssl.HAS_TLSv1_3:
        raise RuntimeError("TLS 1.3 is unavailable in this Python/OpenSSL runtime")
    paths = (
        Path(os.environ.get("F1E_TLS_ENGINE_CERT", "/run/tls/engine.crt")),
        Path(os.environ.get("F1E_TLS_ENGINE_KEY", "/run/tls/engine.key")),
        Path(os.environ.get("F1E_TLS_CA_CERT", "/run/tls/ca.crt")),
    )
    for path in paths:
        if not path.is_file():
            raise RuntimeError("required TLS certificate file is missing")
    config = uvicorn.Config(
        "f1engine.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        workers=1,
        ssl_certfile=str(paths[0]),
        ssl_keyfile=str(paths[1]),
        ssl_ca_certs=str(paths[2]),
        ssl_cert_reqs=ssl.CERT_REQUIRED,
    )
    config.load()
    if config.ssl is None:
        raise RuntimeError("no server TLS context was created")
    config.ssl.minimum_version = ssl.TLSVersion.TLSv1_3
    config.ssl.verify_mode = ssl.CERT_REQUIRED
    config.ssl.check_hostname = False  # server side: clients verified by CA
    return config


def main() -> int:
    try:
        configuration = secure_config()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Secure server startup refused: {error}", file=sys.stderr)
        return 1
    uvicorn.Server(configuration).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
