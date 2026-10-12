"""Offline checks for the optional OpenF1 source MQTT spool."""

from __future__ import annotations

import importlib.util
import json
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "record-openf1-mqtt.py"
    spec = importlib.util.spec_from_file_location("openf1_collector", path)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_normalizer_keeps_provider_sequence_source_hash_and_time() -> None:
    collector = module()
    now = datetime(2026, 10, 11, 12, 30, tzinfo=UTC)
    payload = json.dumps({
        "session_key": 24001, "date": now.isoformat(),
        "position": 1, "driver_number": 1,
        "_id": 1234567, "_key": "driver-1-position",
    }).encode()
    row = collector.normalize_message("v1/position", payload, 24001, now)
    assert row["provider"] == "openf1"
    assert row["providerSequence"] == 1234567
    assert row["providerKey"] == "driver-1-position"
    assert row["rawPayloadText"] == payload.decode()
    assert len(row["rawPayloadSha256"]) == 64
    assert collector.normalize_message("v1/position", payload, 24002, now) is None


def test_normalizer_refuses_bad_session_source_shape_and_future_events() -> None:
    collector = module()
    now = datetime(2026, 10, 11, 12, 30, tzinfo=UTC)
    with pytest.raises(ValueError, match="unauthorized"):
        collector.normalize_message("v1/car_data", b"{}", 1, now)
    with pytest.raises(ValueError, match="UTF-8 JSON"):
        collector.normalize_message("v1/position", b"not-json", 1, now)
    with pytest.raises(ValueError, match="_id"):
        collector.normalize_message(
            "v1/position", b'{"session_key":1,"_key":"x"}', 1, now,
        )
    with pytest.raises(ValueError, match="timestamp|capture clock|event time"):
        data = {
            "session_key": 1, "_id": 9, "_key": "x",
            "date": (now + timedelta(days=1)).isoformat(),
        }
        collector.normalize_message("v1/laps", json.dumps(data).encode(), 1, now)


def test_optional_mqtt_code_does_not_require_install_to_import() -> None:
    assert module().BROKER == "mqtt.openf1.org"
    assert module().PORT == 8883


def test_mqtt_tls_context_requires_tls13_and_verifies_broker() -> None:
    collector = module()
    if not ssl.HAS_TLSv1_3:
        with pytest.raises(RuntimeError, match="TLS 1.3 is required"):
            collector.build_tls_context()
        return
    context = collector.build_tls_context()
    assert isinstance(context, ssl.SSLContext)
    assert context.minimum_version == ssl.TLSVersion.TLSv1_3
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.maximum_version in (
        ssl.TLSVersion.MAXIMUM_SUPPORTED, ssl.TLSVersion.TLSv1_3,
    )


def test_tls13_unavailable_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = module()
    monkeypatch.setattr(ssl, "HAS_TLSv1_3", False)
    with pytest.raises(RuntimeError, match="TLS 1.3 is required"):
        collector.build_tls_context()
