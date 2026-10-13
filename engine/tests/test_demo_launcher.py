"""The plain-HTTP demo launcher must fail closed unless a managed edge is declared."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def launcher():
    path = Path(__file__).resolve().parents[2] / "scripts" / "serve-unified-demo.py"
    spec = importlib.util.spec_from_file_location("serve_unified_demo", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("VERCEL", "F1E_DEMO_MANAGED_EDGE", "F1E_DEMO_TLS_CERT",
                 "F1E_DEMO_TLS_KEY", "F1E_DEMO_LOOPBACK_ONLY"):
        monkeypatch.delenv(name, raising=False)


def test_plain_http_on_an_unmanaged_host_is_refused() -> None:
    with pytest.raises(RuntimeError, match="TLS 1.3 required"):
        launcher().configured_server()


def test_a_declared_managed_edge_allows_plain_http_on_the_injected_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("F1E_DEMO_MANAGED_EDGE", "1")
    monkeypatch.setenv("PORT", "10000")
    config = launcher().configured_server()
    assert config.port == 10000 and config.host == "0.0.0.0"


def test_loopback_flag_cannot_be_combined_with_a_managed_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("F1E_DEMO_MANAGED_EDGE", "1")
    monkeypatch.setenv("F1E_DEMO_LOOPBACK_ONLY", "1")
    with pytest.raises(RuntimeError, match="managed edge"):
        launcher().configured_server()
