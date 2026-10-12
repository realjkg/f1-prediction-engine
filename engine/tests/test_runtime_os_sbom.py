"""Final container package SBOM generation and evidence verification."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ENGINE_ID = "sha256:" + "a" * 64
WEB_ID = "sha256:" + "b" * 64
COMMIT = "c" * 40


def _generator():
    path = Path(__file__).resolve().parents[2] / "scripts" / "generate-runtime-os-sbom.py"
    spec = importlib.util.spec_from_file_location("runtime_os_inventory", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def dumps(tmp_path: Path) -> tuple[Path, Path]:
    engine = tmp_path / "dpkg.tsv"
    web = tmp_path / "apk.txt"
    engine.write_text(
        "ca-certificates\t20240203\n"
        "libssl3t64\t3.0.17-1~deb12u2\n"
        "python3.12\t3.12.10-1\n", encoding="utf-8",
    )
    web.write_text(
        "nginx-1.28.0-r4\n"
        "libcrypto3-3.5.0-r0\n"
        "musl-1.2.5-r9\n", encoding="utf-8",
    )
    return engine, web


def test_exact_reproducibility_and_image_identity(
    dumps: tuple[Path, Path], tmp_path: Path,
) -> None:
    engine, web = dumps
    generator = _generator()
    one = tmp_path / "one" / "runtime.cdx.json"
    two = tmp_path / "two" / "runtime.cdx.json"
    manifest = generator.generate(
        one, engine, web, engine_id=ENGINE_ID, web_id=WEB_ID, commit=COMMIT,
    )
    generator.generate(two, engine, web, engine_id=ENGINE_ID, web_id=WEB_ID, commit=COMMIT)
    assert one.read_bytes() == two.read_bytes()
    assert (
        one.with_suffix(".manifest.json").read_bytes()
        == two.with_suffix(".manifest.json").read_bytes()
    )
    assert manifest["componentCount"] == 6
    assert manifest["ecosystemCounts"] == {"deb": 3, "apk": 3}
    assert generator.verify(one, engine, web) == manifest
    sbom = json.loads(one.read_text(encoding="utf-8"))
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    assert sbom["compositions"][0]["aggregate"] == "incomplete"
    assert len({p["bom-ref"] for p in sbom["components"]}) == 6
    assert all("f1:runtimeImage" in [p["name"] for p in c["properties"]]
               for c in sbom["components"])


def test_tamper_or_package_drift_fails_verification(
    dumps: tuple[Path, Path], tmp_path: Path,
) -> None:
    engine, web = dumps
    generator = _generator()
    path = tmp_path / "runtime.cdx.json"
    generator.generate(
        path, engine, web, engine_id=ENGINE_ID, web_id=WEB_ID, commit=COMMIT,
    )
    web.write_text(web.read_text(encoding="utf-8") + "zlib-1.3.1-r1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="drift"):
        generator.verify(path, engine, web)
    web.write_text("nginx-1.28.0-r4\nlibcrypto3-3.5.0-r0\nmusl-1.2.5-r9\n")
    with path.open("ab") as output:
        output.write(b"tampered")
    with pytest.raises(ValueError, match="digest"):
        generator.verify(path, engine, web)


def test_rejects_non_image_ids_malformed_and_duplicate_packages(
    dumps: tuple[Path, Path],
) -> None:
    generator = _generator()
    engine, web = dumps
    with pytest.raises(ValueError, match="image IDs"):
        generator.build(
            engine.read_bytes(), web.read_bytes(), engine_id="local-latest",
            web_id=WEB_ID, commit=COMMIT,
        )
    with pytest.raises(ValueError, match="Git SHA"):
        generator.build(
            engine.read_bytes(), web.read_bytes(), engine_id=ENGINE_ID,
            web_id=WEB_ID, commit="main",
        )
    with pytest.raises(ValueError, match="duplicate"):
        generator.parse_dpkg("openssl\t1.0\nopenssl\t2.0\n")
    with pytest.raises(ValueError, match="malformed"):
        generator.parse_apk("a totally unversioned package\n")
    with pytest.raises(ValueError, match="malformed"):
        generator.parse_dpkg("no-version\n")
    with pytest.raises(ValueError, match="missing"):
        generator.parse_apk("")
