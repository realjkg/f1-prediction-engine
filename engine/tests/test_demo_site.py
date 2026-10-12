"""Single-origin container demo contract: frontend, API, evidence and gates."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from f1engine.app import ApiSettings
from f1engine.demo_site import create_unified_demo

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def built_inventory(tmp_path: Path) -> Path:
    path = tmp_path / "sbom" / "f1-sbom.cdx.json"
    command = [
        sys.executable, str(ROOT / "scripts" / "generate-sbom.py"),
        "--root", str(ROOT), "--output", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return path


def _settings(snapshot: Path, ledger: Path, inventory: Path) -> ApiSettings:
    return ApiSettings(
        data_dir=snapshot,
        ledger_path=ledger,
        sbom_path=inventory,
        sbom_source_root=ROOT,
    )


def test_one_server_serves_react_and_api(
    predictable_snapshot: Path, ledger_factory, built_inventory: Path,
    tmp_path: Path,
) -> None:
    static = tmp_path / "web"
    static.mkdir()
    (static / "index.html").write_text(
        '<html><body><div id="root">Pit Wall</div></body></html>',
        encoding="utf-8",
    )
    (static / "asset.js").write_text("const demo = 1;", encoding="utf-8")
    settings = _settings(predictable_snapshot, ledger_factory(4, 5), built_inventory)
    app = create_unified_demo(settings=settings, static_dir=static)
    client = TestClient(app)

    home = client.get("/")
    assert home.status_code == 200
    assert "Pit Wall" in home.text
    assert home.headers["cache-control"] == "no-store"
    assert home.headers["x-content-type-options"] == "nosniff"
    assert home.headers["x-frame-options"] == "DENY"

    asset = client.get("/asset.js")
    assert asset.status_code == 200
    assert "const demo" in asset.text

    config = client.get("/api/config")
    assert config.status_code == 200
    assert config.json()["advisoryOnly"] is True
    assert config.json()["briefMode"] == "fixture"
    predicted = client.get("/api/predictions/fourth-grand-prix?season=2021")
    assert predicted.status_code == 200
    assert predicted.json()["total"] == 1
    assert client.get("/api/supply-chain").status_code == 200

    for path in ("/metrics", "/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
    assert client.get("/api/not-a-route").status_code == 404
    assert client.get("/fake-file.js").status_code == 404


def test_startup_refuses_missing_web_evidence_and_unverifiable_sbom(
    predictable_snapshot: Path, ledger_factory, built_inventory: Path,
    tmp_path: Path,
) -> None:
    ledger = ledger_factory(4)
    settings = _settings(predictable_snapshot, ledger, built_inventory)
    with pytest.raises(RuntimeError, match="web bundle"):
        create_unified_demo(settings=settings, static_dir=tmp_path / "missing")
    site = tmp_path / "web"
    site.mkdir()
    (site / "index.html").write_text("<div>UI</div>", encoding="utf-8")
    with pytest.raises(RuntimeError, match="prebuilt immutable"):
        create_unified_demo(
            settings=_settings(
                predictable_snapshot, tmp_path / "no-ledger.jsonl", built_inventory
            ),
            static_dir=site,
        )
    altered_root = tmp_path / "modified"
    for rel in (
        "engine/requirements.lock.txt", "engine/requirements-dev.lock.txt",
        "web/package-lock.json",
    ):
        dest = altered_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest)
    (altered_root / "engine/requirements.lock.txt").write_text(
        "changed", encoding="utf-8",
    )
    with pytest.raises(Exception, match="source lock changed"):
        create_unified_demo(
            settings=ApiSettings(
                data_dir=predictable_snapshot,
                ledger_path=ledger,
                sbom_path=built_inventory,
                sbom_source_root=altered_root,
            ),
            static_dir=site,
        )
