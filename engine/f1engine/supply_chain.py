"""Read a generated, integrity-checked lockfile SBOM as API-safe inventory.

The artifact is not a release attestation or evidence of installed container
and mobile packages. Every requested read verifies the source digests and
manifest to prevent serving stale lockfile inventory as a current build.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from f1engine.wire import WireModel


class SupplyChainError(ValueError):
    code = "SBOM_INVALID"


class SupplyChainUnavailable(SupplyChainError):
    code = "SBOM_UNAVAILABLE"


class SupplyChainComponent(WireModel):
    ecosystem: Literal["pypi", "npm"]
    name: str
    version: str
    scope: Literal["required", "optional"]
    license: str | None = None


class SupplyChainView(WireModel):
    status: Literal["lockfile-inventory-only"] = "lockfile-inventory-only"
    spec_version: Literal["1.6"] = "1.6"
    sbom_sha256: str
    source_digests: dict[str, str]
    total_components: int
    ecosystem_counts: dict[str, int]
    components: tuple[SupplyChainComponent, ...]
    limitations: tuple[str, ...]
    release_ready: Literal[False] = False


def read_supply_chain(sbom_path: Path, *, source_root: Path) -> SupplyChainView:
    manifest_path = sbom_path.with_suffix(".manifest.json")
    if not sbom_path.is_file() or not manifest_path.is_file():
        raise SupplyChainUnavailable("No generated CycloneDX inventory configured")
    try:
        data = sbom_path.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sbom = json.loads(data)
        if manifest["sbomSha256"] != hashlib.sha256(data).hexdigest():
            raise SupplyChainError("SBOM digest differs from manifest")
        if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.6":
            raise SupplyChainError("unsupported SBOM format or version")
        locks = manifest["sourceDigests"]
        expected = {
            "engine/requirements.lock.txt",
            "engine/requirements-dev.lock.txt",
            "web/package-lock.json",
        }
        if set(locks) != expected:
            raise SupplyChainError("manifest is missing pinned source inventory")
        for relpath, digest in locks.items():
            path = source_root / relpath
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise SupplyChainError(f"source lock changed since SBOM: {relpath}")
        components = []
        for raw in sbom["components"]:
            properties = {p["name"]: p["value"] for p in raw["properties"]}
            eco = properties["f1:ecosystem"]
            license_value = raw.get("licenses", [])
            license_name = (
                license_value[0]["license"].get("name")
                if license_value else None
            )
            components.append(SupplyChainComponent(
                ecosystem=eco, name=raw["name"],
                version=raw["version"], scope=raw["scope"],
                license=license_name,
            ))
        if len(components) != manifest["componentCount"]:
            raise SupplyChainError("manifest component count mismatches SBOM")
        counts = {
            eco: sum(c.ecosystem == eco for c in components)
            for eco in ("pypi", "npm")
        }
        if counts != manifest["ecosystemCounts"]:
            raise SupplyChainError("manifest ecosystem counts mismatch")
        return SupplyChainView(
            sbom_sha256=manifest["sbomSha256"],
            source_digests=locks,
            total_components=len(components),
            ecosystem_counts=counts,
            components=tuple(components),
            limitations=tuple(manifest["limitations"]),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, SupplyChainError):
            raise
        raise SupplyChainError("Cannot validate SBOM or its source manifest") from exc
