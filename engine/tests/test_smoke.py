"""Scaffold smoke tests — seams import, the app factory works, stubs refuse.

Each seam's real behavior is tested by its owning task; this file pins the
skeleton: the package imports, the FastAPI factory serves health, and every
stub raises NotImplementedError rather than guessing.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from f1engine.app import APP_TITLE, create_app
from f1engine.ensemble import arbitrate
from f1engine.evidence import append_record, verify_chain
from f1engine.features import build_asof_features
from f1engine.ingestion import load_snapshot
from f1engine.models import MODEL_IDS
from f1engine.observability import Signal


def test_all_model_ids_are_pinned() -> None:
    assert MODEL_IDS == ("m1-gbm", "m2-logit", "m3-form")


def test_production_signals_are_in_the_closed_enum() -> None:
    assert {signal.value for signal in Signal} >= {
        "data-ingest",
        "prediction-latency",
        "prediction-disagreement",
        "backtest-accuracy",
    }


def test_create_app_serves_health() -> None:
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}
    assert APP_TITLE == "F1 Prediction Engine"


def test_stubs_raise_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        load_snapshot(Path("data/snapshot"))
    with pytest.raises(NotImplementedError):
        build_asof_features({}, through_round=1)
    with pytest.raises(NotImplementedError):
        arbitrate([], weights={})
    with pytest.raises(NotImplementedError):
        append_record(Path("ledger.jsonl"), record={})
    with pytest.raises(NotImplementedError):
        verify_chain(Path("ledger.jsonl"))
