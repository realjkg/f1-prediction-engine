"""FastAPI application factory.

Scaffold surface: /healthz only. Prediction, models, evidence, events, and
metrics endpoints are added by their owning tasks against the shared
prediction-record contract (spec: "Two runtimes, one evidence contract").
"""

from fastapi import FastAPI

APP_TITLE = "F1 Prediction Engine"
APP_VERSION = "0.1.0"


def create_app() -> FastAPI:
    """Create the engine API app (scaffold: health surface only)."""
    app = FastAPI(title=APP_TITLE, version=APP_VERSION)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": APP_VERSION}

    return app
