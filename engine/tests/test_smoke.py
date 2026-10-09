"""Scaffold smoke tests — seams import, the app factory works, seams refuse.

Each seam's real behavior is tested by its owning task; this file pins the
skeleton: the package imports, the FastAPI factory serves health, and
degenerate inputs are refused with typed errors rather than guessed at.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from f1engine.app import APP_TITLE, create_app
from f1engine.ensemble import EnsembleInvalidInput, arbitrate
from f1engine.evidence import EvidenceRecordInvalid, append_record
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


def test_arbitrate_refuses_empty_input() -> None:
    with pytest.raises(EnsembleInvalidInput):
        arbitrate([], weights={})


def test_append_record_refuses_schema_failures(tmp_path: Path) -> None:
    with pytest.raises(EvidenceRecordInvalid):
        append_record(tmp_path / "ledger.jsonl", record={})
