"""API contract tests — the read surface over ledger + snapshot.

Spec row "API": status codes + response schema per endpoint, advisory fields
present on prediction-bearing responses, 404s for unknown races, a valid
Prometheus exposition on /metrics, and typed 503s (never tracebacks) when
the ledger fails verification. Records are written through the real pipeline
(trained models -> arbitrated verdict -> append_record) against the
predictable mini snapshot, so the API is tested against the records the
engine actually writes.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from f1engine.app import (
    APP_VERSION,
    ApiSettings,
    EventSource,
    EventView,
    create_app,
)
from f1engine.ensemble import PODIUM_SPREAD_OK_THRESHOLD
from f1engine.ingestion import PinnedDataset, SnapshotVersionMismatch
from f1engine.observability import EventStatus, Signal

EVIDENCE_BASIS = "REAL MODELS — PINNED DATASET 2020–2024 — NO LIVE INFERENCE"
EVENT_TIME = "2026-10-09T12:00:00Z"

# Label values may themselves contain braces (a route template like
# /api/predictions/{race_id} inside path="...") — match to the final brace.
_PROMETHEUS_SAMPLE = re.compile(
    r"^[a-zA-Z_:][a-zA-Z0-9_:]*(\{.*\})? [0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$"
)


# ---------------------------------------------------------------------------
# Fixtures and helpers — records built through the real pipeline.
# ---------------------------------------------------------------------------


def _client(
    dataset: PinnedDataset,
    ledger: Path | None = None,
    *,
    settings: ApiSettings | None = None,
    event_source: EventSource | None = None,
) -> TestClient:
    base = settings if settings is not None else ApiSettings()
    resolved = replace(base, ledger_path=ledger) if ledger is not None else base
    return TestClient(
        create_app(resolved, dataset=dataset, event_source=event_source)
    )


def _tampered_copy(ledger_path: Path) -> Path:
    """Re-serialize the first record with two winner probabilities nudged —
    schema-valid content that no longer matches its own recorded hash."""
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    winner = record["ensemble"]["winner"]
    drivers = list(winner)
    winner[drivers[0]] += 0.01
    winner[drivers[1]] -= 0.01
    lines[0] = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    tampered = ledger_path.with_name("tampered.jsonl")
    tampered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tampered


class ScriptedEvents:
    """A stand-in EventSource — the observability bus does not exist yet."""

    def __init__(self, events: Sequence[EventView]) -> None:
        self._events = events

    def list_events(self) -> Sequence[EventView]:
        return self._events


def _scripted_events() -> list[EventView]:
    return [
        EventView(
            signal=Signal.DATA_INGEST,
            status=EventStatus.OK,
            occurred_at=EVENT_TIME,
            detail={"tables": 6},
        ),
        EventView(
            signal=Signal.PREDICTION_DISAGREEMENT,
            status=EventStatus.DEGRADED,
            occurred_at=EVENT_TIME,
            detail={"raceId": "fourth-grand-prix"},
        ),
    ]


# ---------------------------------------------------------------------------
# /api/races
# ---------------------------------------------------------------------------


def test_races_serve_the_snapshot_catalog(predictable_dataset: PinnedDataset) -> None:
    client = _client(predictable_dataset)

    response = client.get("/api/races")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(predictable_dataset.races)
    assert len(body["races"]) == body["total"]
    first = body["races"][0]
    assert set(first) == {"season", "round", "raceId", "name", "date", "completed"}
    assert (first["season"], first["round"]) == (2021, 1)
    assert all(race["completed"] for race in body["races"])


def test_races_flag_rounds_without_results(predictable_dataset: PinnedDataset) -> None:
    client = _client(replace(predictable_dataset, results=()))

    body = client.get("/api/races").json()
    assert body["total"] > 0
    assert all(race["completed"] is False for race in body["races"])


# ---------------------------------------------------------------------------
# /api/predictions/{race_id}
# ---------------------------------------------------------------------------


def test_predictions_serve_the_record_contract(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4, 5))

    response = client.get("/api/predictions/fourth-grand-prix")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    record = body["predictions"][0]
    assert record["schemaVersion"] == 1
    assert record["predictionId"] == "2021-r4-fourth-grand-prix"
    assert record["advisoryOnly"] is True
    assert record["evidenceBasis"] == EVIDENCE_BASIS
    assert record["dataLimitations"] == list(predictable_dataset.limitations)
    assert len(record["dataLimitations"]) > 0
    assert record["dataset"]["id"] == predictable_dataset.dataset_id
    assert record["dataset"]["sha256"] == predictable_dataset.dataset_sha256
    assert set(record["models"]) == {"m1-gbm", "m2-logit", "m3-form"}
    for model in record["models"].values():
        assert model["raceId"] == "fourth-grand-prix"
        assert model["diagnostics"]["trainedThroughRound"] == 4
    ensemble = record["ensemble"]
    assert ensemble["raceId"] == "fourth-grand-prix"
    assert ensemble["consensus"]["flag"] in ("OK", "LOW_CONSENSUS")
    assert set(ensemble["weightsUsed"]) == {"m1-gbm", "m2-logit", "m3-form"}
    assert len(record["recordSha256"]) == 64


def test_unknown_races_404_with_a_typed_code(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4, 5))

    response = client.get("/api/predictions/no-such-grand-prix")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "RACE_UNKNOWN"


def test_races_without_records_404_with_a_typed_code(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4))  # round 5 not predicted

    response = client.get("/api/predictions/fifth-grand-prix")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PREDICTIONS_NOT_FOUND"


# ---------------------------------------------------------------------------
# /api/evidence
# ---------------------------------------------------------------------------


def test_evidence_pages_the_verified_ledger(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4, 5))

    full = client.get("/api/evidence").json()
    assert full["total"] == 2
    assert full["chainValid"] is True
    assert [record["predictionId"] for record in full["records"]] == [
        "2021-r4-fourth-grand-prix",
        "2021-r5-fifth-grand-prix",
    ]

    page = client.get("/api/evidence", params={"offset": 1, "limit": 1}).json()
    assert (page["offset"], page["limit"]) == (1, 1)
    assert [record["predictionId"] for record in page["records"]] == [
        "2021-r5-fifth-grand-prix"
    ]

    rejected = client.get("/api/evidence", params={"limit": 0})
    assert rejected.status_code == 422


def test_an_absent_ledger_is_empty_not_broken(
    predictable_dataset: PinnedDataset, tmp_path: Path
) -> None:
    client = _client(predictable_dataset, tmp_path / "absent.jsonl")

    evidence = client.get("/api/evidence").json()
    assert evidence["records"] == []
    assert evidence["total"] == 0
    assert client.get("/api/predictions/fourth-grand-prix").status_code == 404


def test_a_tampered_ledger_is_refused_with_typed_503s(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, _tampered_copy(ledger_factory(4, 5)))

    for endpoint in ("/api/evidence", "/api/predictions/fourth-grand-prix"):
        response = client.get(endpoint)
        assert response.status_code == 503, endpoint
        assert response.json()["detail"]["code"] == "EVIDENCE_TAMPERED", endpoint


def test_an_unparseable_ledger_is_refused_with_a_typed_503(
    predictable_dataset: PinnedDataset, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.jsonl"
    broken.write_text("not-json\n", encoding="utf-8")
    client = _client(predictable_dataset, broken)

    response = client.get("/api/evidence")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "EVIDENCE_SCHEMA_INVALID"


# ---------------------------------------------------------------------------
# /api/models, /api/events, /api/config
# ---------------------------------------------------------------------------


def test_models_serve_the_roster(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4))

    body = client.get("/api/models").json()
    assert [model["modelId"] for model in body["models"]] == [
        "m1-gbm",
        "m2-logit",
        "m3-form",
        "ensemble",
    ]
    for model in body["models"]:
        assert model["method"]
        assert model["role"]
    assert body["models"][-1]["consensusThreshold"] == PODIUM_SPREAD_OK_THRESHOLD
    assert all(model["consensusThreshold"] is None for model in body["models"][:3])


def test_events_serve_the_closed_signal_store(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(
        predictable_dataset,
        ledger_factory(4),
        event_source=ScriptedEvents(_scripted_events()),
    )

    body = client.get("/api/events").json()
    assert body["total"] == 2
    assert [event["signal"] for event in body["events"]] == [
        "data-ingest",
        "prediction-disagreement",
    ]
    assert body["events"][0]["status"] == "ok"
    assert body["events"][1]["status"] == "degraded"
    assert body["events"][0]["occurredAt"] == EVENT_TIME


def test_events_default_to_the_empty_store(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4))

    assert client.get("/api/events").json() == {"events": [], "total": 0}


def test_config_serves_the_operating_contract(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4))

    body = client.get("/api/config").json()
    assert body["engineVersion"] == APP_VERSION
    assert body["datasetVersion"] == predictable_dataset.dataset_id
    assert body["advisoryOnly"] is True
    assert "advisory" in body["advisoryNotice"].lower()
    assert body["consensusThreshold"] == PODIUM_SPREAD_OK_THRESHOLD
    assert body["briefMode"] == "fixture"  # the safe default


def test_config_reflects_the_configured_brief_mode(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(
        predictable_dataset,
        ledger_factory(4),
        settings=ApiSettings(brief_mode="live"),
    )

    assert client.get("/api/config").json()["briefMode"] == "live"


def test_brief_mode_env_parsing_fails_toward_fixture() -> None:
    assert ApiSettings.from_env({"F1E_BRIEF_MODE": "live"}).brief_mode == "live"
    assert ApiSettings.from_env({"F1E_BRIEF_MODE": "bogus"}).brief_mode == "fixture"
    assert ApiSettings.from_env({}).brief_mode == "fixture"


# ---------------------------------------------------------------------------
# /metrics
# ---------------------------------------------------------------------------


def test_metrics_serve_valid_prometheus_exposition(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4))
    client.get("/api/races")
    client.get("/api/predictions/fourth-grand-prix")

    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")

    lines = response.text.splitlines()
    samples = [line for line in lines if line and not line.startswith("#")]
    assert samples
    assert all(_PROMETHEUS_SAMPLE.match(line) for line in samples)
    types = {line.split()[2] for line in lines if line.startswith("# TYPE")}
    assert {
        "f1engine_build_info",
        "f1engine_http_requests_total",
        "f1engine_http_request_duration_seconds",
    } <= types
    assert any(line.startswith("f1engine_build_info{") for line in samples)
    assert any(
        'path="/api/races"' in line and 'status="200"' in line for line in samples
    )
    # Parameterized routes are labeled by template, never by the requested id.
    assert any('path="/api/predictions/{race_id}"' in line for line in samples)


# ---------------------------------------------------------------------------
# CORS and startup refusal
# ---------------------------------------------------------------------------


def test_cors_serves_the_configured_dev_origins(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4))

    response = client.get("/api/races", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

    preflight = client.options(
        "/api/races",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_ignores_unlisted_origins(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4))

    response = client.get("/api/races", headers={"Origin": "https://unlisted.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_origins_are_configurable(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(
        predictable_dataset,
        ledger_factory(4),
        settings=ApiSettings(cors_origins=("https://pitwall.example",)),
    )

    response = client.get("/api/races", headers={"Origin": "https://pitwall.example"})
    assert response.headers["access-control-allow-origin"] == "https://pitwall.example"


def test_startup_refuses_a_mismatched_snapshot(
    predictable_snapshot: Path, tmp_path: Path
) -> None:
    copied = Path(shutil.copytree(predictable_snapshot, tmp_path / "snapshot"))
    (copied / "DATASET_VERSION").write_text("9999.99.9", encoding="utf-8")

    with pytest.raises(SnapshotVersionMismatch):
        create_app(ApiSettings(data_dir=copied))
