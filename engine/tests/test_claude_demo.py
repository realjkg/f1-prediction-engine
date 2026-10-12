"""Claude demo is opt-in, authenticated, evidence-pinned and read-only."""

from __future__ import annotations

import ssl
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from f1engine.app import ApiSettings, create_app
from f1engine.claude_demo import (
    ClaudeDemoSettings,
    authenticated,
    evidence_payload,
    register_claude_demo,
    tls_context,
)

ACCESS = "a" * 32
KEY = "b" * 32


def configured() -> ClaudeDemoSettings:
    return ClaudeDemoSettings(
        enabled=True, gateway_key=KEY,
        access_token=ACCESS, model="anthropic/claude-sonnet-5",
    )


def test_claude_auth_and_model_allowlist_fail_closed() -> None:
    assert configured().configured()
    assert authenticated(ACCESS, ACCESS)
    assert not authenticated(ACCESS, ACCESS[:-1] + "b")
    assert not authenticated(ACCESS, None)
    assert not ClaudeDemoSettings.from_env().configured()
    assert not replace(configured(), model="openai/gpt-6").configured()
    assert not replace(configured(), access_token="short").configured()
    assert not replace(configured(), gateway_key=ACCESS).configured()


def test_claude_tls_outbound_requires_tls13(monkeypatch: pytest.MonkeyPatch) -> None:
    if ssl.HAS_TLSv1_3:
        context = tls_context()
        assert context.minimum_version == ssl.TLSVersion.TLSv1_3
        assert context.check_hostname is True
        assert context.verify_mode == ssl.CERT_REQUIRED
    monkeypatch.setattr(ssl, "HAS_TLSv1_3", False)
    with pytest.raises(RuntimeError, match="TLS 1.3"):
        tls_context()


def _client(dataset, path: Path, *, settings=None, gateway=None) -> TestClient:
    app = create_app(ApiSettings(ledger_path=path), dataset=dataset)
    register_claude_demo(
        app, ledger_path=path, settings=settings or configured(),
        gateway=gateway or (lambda evidence, *, model, key: "Evidence-only historical brief."),
    )
    return TestClient(app)


def test_claude_demo_is_disabled_without_credentials(
    predictable_dataset, ledger_factory,
) -> None:
    ledger = ledger_factory(4)
    client = _client(
        predictable_dataset, ledger,
        settings=ClaudeDemoSettings(
            enabled=False, gateway_key="", access_token="", model="anthropic/claude-sonnet-5",
        ),
    )
    response = client.post(
        "/api/claude/brief", json={"season": 2021, "raceId": "fourth-grand-prix"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CLAUDE_UNAVAILABLE"


def test_claude_demo_does_not_invoke_gateway_without_authorization(
    predictable_dataset, ledger_factory,
) -> None:
    calls: list[object] = []
    client = _client(
        predictable_dataset, ledger_factory(4),
        gateway=lambda evidence, *, model, key: calls.append(evidence) or "Should never run",
    )
    path = "/api/claude/brief"
    request = {"season": 2021, "raceId": "fourth-grand-prix"}
    for token in (None, "wrong"):
        headers = {} if token is None else {"X-F1E-Demo-Access": token}
        denied = client.post(path, json=request, headers=headers)
        assert denied.status_code == 403
    assert calls == []


def test_claude_demo_references_only_frozen_pre_race_prediction(
    predictable_dataset, ledger_factory,
) -> None:
    calls: list[dict] = []

    def gateway(evidence, *, model, key):
        calls.append({"evidence": evidence, "model": model, "key": key})
        return "This historical ensemble highlights a likely contender, not a live prediction."

    ledger = ledger_factory(4)
    client = _client(predictable_dataset, ledger, gateway=gateway)
    response = client.post(
        "/api/claude/brief",
        headers={"X-F1E-Demo-Access": ACCESS},
        json={"season": 2021, "raceId": "fourth-grand-prix"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["historicalReplay"] is True
    assert body["advisoryOnly"] is True
    assert body["modelPredictsOutcomes"] is False
    assert body["raceId"] == "fourth-grand-prix"
    assert len(body["recordSha256"]) == 64
    assert len(body["evidenceSha256"]) == 64
    assert calls[0]["model"] == "anthropic/claude-sonnet-5"
    assert calls[0]["key"] == KEY
    sent = calls[0]["evidence"]
    assert sent["race"]["id"] == "fourth-grand-prix"
    assert sent["raceResultsIncluded"] is False
    assert "classified" not in str(sent).lower()
    assert "actual" not in str(sent).lower()
    assert abs(sum(d["ensembleWinProbability"] for d in sent["leaderCandidates"]) - 1) <= 1
    missing = client.post(
        "/api/claude/brief",
        headers={"X-F1E-Demo-Access": ACCESS},
        json={"season": 2021, "raceId": "nonexistent"},
    )
    assert missing.status_code == 404
    assert len(calls) == 1


def test_claude_rejects_tampered_ledger_without_outbound_request(
    predictable_dataset, ledger_factory,
) -> None:
    calls = []
    ledger = ledger_factory(4)
    ledger.write_text(ledger.read_text().replace("prediction", "predicTion", 1))
    client = _client(
        predictable_dataset, ledger,
        gateway=lambda evidence, *, model, key: calls.append(evidence) or "BAD",
    )
    response = client.post(
        "/api/claude/brief",
        headers={"X-F1E-Demo-Access": ACCESS},
        json={"season": 2021, "raceId": "fourth-grand-prix"},
    )
    assert response.status_code == 503
    assert calls == []
