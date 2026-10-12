"""Single-process F1 demo: built React assets + read-only FastAPI.

The historical dataset and deterministic evidence ledger are baked into the
deployment artifact. No MQTT daemon, model training or mutable predictions run
inside a request-serving Vercel instance.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from f1engine.app import ApiSettings, create_app
from f1engine.evidence import verify_chain
from f1engine.ingestion import load_snapshot
from f1engine.supply_chain import read_supply_chain


def create_unified_demo(
    *, settings: ApiSettings | None = None, static_dir: Path | None = None,
) -> FastAPI:
    """Serve app and API at one origin; fail on absent build evidence."""
    settings = settings if settings is not None else ApiSettings.from_env()
    static_dir = static_dir if static_dir is not None else Path(
        os.environ.get("F1E_DEMO_WEB_DIR", "/app/web/dist")
    )
    if not static_dir.is_dir() or not (static_dir / "index.html").is_file():
        raise RuntimeError("Unified demo web bundle missing at startup")
    if not settings.ledger_path.is_file():
        raise RuntimeError("Unified demo requires prebuilt immutable prediction evidence")
    # These checks run at startup so a cold-start never presents partial proof.
    load_snapshot(settings.data_dir)
    verify_chain(settings.ledger_path)
    read_supply_chain(settings.sbom_path, source_root=settings.sbom_source_root)
    app = create_app(settings)

    @app.middleware("http")
    async def public_demo_security(request, call_next):
        # Keep diagnostics and interactive API schemas out of the public demo.
        if request.url.path in ("/metrics", "/docs", "/redoc", "/openapi.json"):
            return PlainTextResponse("Not found", status_code=404)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; object-src 'none'; "
            "frame-ancestors 'none'; connect-src 'self' https:; "
            "script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "manifest-src 'self'; worker-src 'self'"
        )
        # HSTS applies to browsers at a real HTTPS edge; Vercel terminates it.
        if request.url.scheme == "https" or os.environ.get("VERCEL") == "1":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        if request.url.path.startswith("/api/") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response

    # Register static files *last* so /api/ and /healthz keep their authority.
    # The React UI uses hash routes; no arbitrary-path SPA fallback is needed.
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="demo-web")
    return app
