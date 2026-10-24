"""Privacy regressions: no per-visitor access logs, no credentials in error text."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(script: str):
    path = ROOT / "scripts" / script
    spec = importlib.util.spec_from_file_location(script.replace("-", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unified_demo_server_keeps_no_access_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("F1E_DEMO_LOOPBACK_ONLY", "1")
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("F1E_DEMO_MANAGED_EDGE", raising=False)
    config = _load("serve-unified-demo.py").configured_server()
    assert config.access_log is False


@pytest.mark.parametrize("conf", ["deploy/nginx.conf", "deploy/nginx-tls.conf"])
def test_nginx_server_blocks_turn_access_logging_off(conf: str) -> None:
    text = (ROOT / conf).read_text(encoding="utf-8")
    assert re.search(r"^\s*access_log off;", text, re.MULTILINE)
    assert "log_format" not in text


def test_every_uvicorn_launch_disables_access_logs() -> None:
    entrypoint = (ROOT / "deploy/engine-entrypoint.sh").read_text(encoding="utf-8")
    assert "--no-access-log" in entrypoint
    for script in ("serve-tls13.py", "serve-unified-demo.py", "demo.py"):
        text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        assert re.search(r"access_log\"?\s*[:=]\s*False", text), script


def test_failed_token_exchange_never_echoes_the_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from f1engine.openf1_feed import fetch_access_token

    secret = "hunter2-do-not-log"

    def refuse(request, timeout, context):
        raise OSError(f"connection reset while sending {request.data!r}")

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    with pytest.raises(ValueError) as caught:
        fetch_access_token("someone@example.com", secret)
    assert secret not in str(caught.value)
    assert "someone@example.com" not in str(caught.value)
