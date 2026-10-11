"""Lockfile SBOM provenance tests and API fail-closed inventory contract."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from f1engine.app import ApiSettings, create_app
from f1engine.supply_chain import (
    SupplyChainError,
    SupplyChainUnavailable,
    read_supply_chain,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate-sbom.py"
LOCKS = (
    "engine/requirements.lock.txt",
    "engine/requirements-dev.lock.txt",
    "web/package-lock.json",
)


def generator_module():
    spec = importlib.util.spec_from_file_location("f1_sbom_generator", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def prepared_source(tmp_path: Path) -> Path:
    root = tmp_path / "build"
    for relative in LOCKS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    return root


def test_cyclonedx_generation_is_reproducible_and_bound_to_pins(tmp_path: Path) -> None:
    root = prepared_source(tmp_path)
    path = root / "data/sbom/f1-sbom.cdx.json"
    generator = generator_module()
    first = generator.generate(root, path)
    raw = path.read_bytes()
    second = generator.generate(root, path)
    assert raw == path.read_bytes()
    assert first == second
    body = json.loads(raw)
    assert body["bomFormat"] == "CycloneDX"
    assert body["specVersion"] == "1.6"
    assert body["compositions"][0]["aggregate"] == "incomplete"
    assert len(body["components"]) == first["componentCount"]
    assert first["ecosystemCounts"]["pypi"] > 10
    assert first["ecosystemCounts"]["npm"] > 100
    view = read_supply_chain(path, source_root=root)
    assert view.release_ready is False
    assert view.total_components == len(view.components)
    assert view.sbom_sha256 == first["sbomSha256"]
    assert any(c.ecosystem == "pypi" and c.name == "fastapi" for c in view.components)
    assert any(c.ecosystem == "npm" and c.name == "react" for c in view.components)


def test_source_lock_changes_make_inventory_unservable(tmp_path: Path) -> None:
    root = prepared_source(tmp_path)
    path = root / "data/sbom/f1-sbom.cdx.json"
    generator_module().generate(root, path)
    with (root / LOCKS[0]).open("a", encoding="utf-8") as out:
        out.write("# malicious/untracked post-build change\n")
    with pytest.raises(SupplyChainError, match="source lock changed"):
        read_supply_chain(path, source_root=root)


def test_corrupted_sbom_and_manifest_are_rejected(tmp_path: Path) -> None:
    root = prepared_source(tmp_path)
    path = root / "data/sbom/f1-sbom.cdx.json"
    generator_module().generate(root, path)
    original = path.read_bytes()
    path.write_bytes(original.replace(b"fastapi", b"fakeapi", 1))
    with pytest.raises(SupplyChainError, match="SBOM digest"):
        read_supply_chain(path, source_root=root)
    path.write_bytes(original)
    manifest = path.with_suffix(".manifest.json")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["componentCount"] += 1
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SupplyChainError, match="count"):
        read_supply_chain(path, source_root=root)


def test_sbom_api_refuses_missing_and_serves_only_verified_inventory(
    predictable_dataset, tmp_path: Path,
) -> None:
    source = prepared_source(tmp_path)
    path = source / "data/sbom/f1-sbom.cdx.json"
    missing = TestClient(create_app(
        ApiSettings(sbom_path=path, sbom_source_root=source),
        dataset=predictable_dataset,
    ))
    refused = missing.get("/api/supply-chain")
    assert refused.status_code == 503
    assert refused.json()["detail"]["code"] == "SBOM_UNAVAILABLE"

    generator_module().generate(source, path)
    response = missing.get("/api/supply-chain")
    assert response.status_code == 200
    body = response.json()
    assert body["releaseReady"] is False
    assert body["totalComponents"] > 100
    assert body["status"] == "lockfile-inventory-only"
    assert len(body["sbomSha256"]) == 64

    path.write_text("not-json", encoding="utf-8")
    refused = missing.get("/api/supply-chain")
    assert refused.status_code == 503
    assert refused.json()["detail"]["code"] == "SBOM_INVALID"


def test_malformed_lockfiles_are_not_invented(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    for relative in LOCKS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="pinned Python"):
        generator_module().generate(root, root / "out.json")
    with pytest.raises(SupplyChainUnavailable):
        read_supply_chain(root / "missing.json", source_root=root)
