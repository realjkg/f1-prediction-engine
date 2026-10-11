#!/usr/bin/env python3
"""Deterministic CycloneDX 1.6 inventory from pinned Python/npm lockfiles.

Scope: application dependency declarations, not installed container OS
packages, native SDKs, or build provenance. No vulnerability or licensing
clearance is inferred from the presence of a component in this inventory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCKS = (
    "engine/requirements.lock.txt",
    "engine/requirements-dev.lock.txt",
    "web/package-lock.json",
)
REQ_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+\-]+)(?:\\\\|\\s|$)", re.M)
PY_CANON = re.compile(r"[-_.]+")
LIMITATIONS = [
    "Lockfile inventory only, not a scan of deployed container or native mobile binaries",
    "Python archive hash alternatives are not installed-artifact attestations",
    "Operating-system packages, transitive native frameworks and service dependencies excluded",
    "Licenses absent from source lockfiles remain unknown; no license clearance implied",
    "No build signature, image digest binding, vulnerability attestation or deployment evidence",
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def python_locks(runtime: str, develop: str) -> list[dict[str, object]]:
    def parse(raw: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for match in REQ_PATTERN.finditer(raw):
            key = PY_CANON.sub("-", match.group(1).lower())
            version = match.group(2)
            if key in found and found[key] != version:
                raise ValueError(f"conflicting Python package pins: {key}")
            found[key] = version
        if not found:
            raise ValueError("no parseable fully pinned Python lock entries")
        return found

    core, all_packages = parse(runtime), parse(develop)
    if not all(all_packages.get(name) == version for name, version in core.items()):
        raise ValueError("Python runtime packages drift from dev lock")
    components: list[dict[str, object]] = []
    for name, version in sorted(all_packages.items()):
        scope = "required" if name in core else "optional"
        components.append({
            "type": "library",
            "bom-ref": f"pypi:{name}@{version}",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name}@{version}",
            "scope": scope,
            "properties": [
                {"name": "f1:ecosystem", "value": "pypi"},
                {"name": "f1:sourceLock", "value": (
                    "engine/requirements.lock.txt" if scope == "required"
                    else "engine/requirements-dev.lock.txt"
                )},
            ],
        })
    return components


def npm_lock(raw: str) -> list[dict[str, object]]:
    lock = json.loads(raw)
    if lock.get("lockfileVersion") not in (2, 3) or not isinstance(lock.get("packages"), dict):
        raise ValueError("expected npm v2/v3 lock with package tree")
    components: list[dict[str, object]] = []
    for path, package in sorted(lock["packages"].items()):
        if not path:
            continue  # local application root, represented in metadata
        if not isinstance(package, dict) or not isinstance(package.get("version"), str):
            raise ValueError(f"unversioned or malformed npm package at {path}")
        name = path.rsplit("node_modules/", 1)[-1]
        if not name or name == path:
            raise ValueError(f"invalid node_modules package path: {path}")
        # pnpm/npm path nesting is preserved as the unique component identity.
        scope = "optional" if package.get("dev", False) else "required"
        from urllib.parse import quote
        comp: dict[str, object] = {
            "type": "library", "bom-ref": f"npm:{path}@{package['version']}",
            "name": name, "version": package["version"],
            "purl": f"pkg:npm/{quote(name, safe='/')}@{package['version']}",
            "scope": scope,
            "properties": [
                {"name": "f1:ecosystem", "value": "npm"},
                {"name": "f1:packagePath", "value": path},
                {"name": "f1:sourceLock", "value": "web/package-lock.json"},
            ],
        }
        license_value = package.get("license")
        if isinstance(license_value, str) and license_value.strip():
            comp["licenses"] = [{"license": {"name": license_value}}]
        components.append(comp)
    if not components:
        raise ValueError("npm lock contained no packages")
    return components


def build_inventory(root: Path) -> tuple[dict[str, object], dict[str, object]]:
    inputs = {path: (root / path).read_bytes() for path in LOCKS}
    digests = {path: sha256(raw) for path, raw in inputs.items()}
    components = python_locks(
        inputs[LOCKS[0]].decode("utf-8"), inputs[LOCKS[1]].decode("utf-8"),
    )
    components.extend(npm_lock(inputs[LOCKS[2]].decode("utf-8")))
    refs = [str(component["bom-ref"]) for component in components]
    if len(refs) != len(set(refs)):
        raise ValueError("duplicate SBOM component references")
    root_fingerprint = sha256(json.dumps(digests, sort_keys=True).encode())
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, f"f1-pitwall/sbom/{root_fingerprint}")
    sbom: dict[str, object] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{identifier}",
        "version": 1,
        "metadata": {"component": {
            "type": "application", "name": "f1-pitwall",
            "version": "0.1.0", "bom-ref": "application:f1-pitwall",
        }},
        "components": components,
        "compositions": [{"aggregate": "incomplete"}],
        "properties": [
            {"name": "f1:coverage", "value": "Python runtime/dev + npm lockfiles only"},
            *(
                {"name": f"f1:sha256:{path}", "value": digest}
                for path, digest in sorted(digests.items())
            ),
        ],
    }
    summary = {
        "status": "lockfile-inventory-only",
        "specVersion": "1.6",
        "sourceDigests": digests,
        "componentCount": len(components),
        "ecosystemCounts": {
            eco: sum(
                1 for c in components if any(
                    p.get("name") == "f1:ecosystem" and p.get("value") == eco
                    for p in c["properties"]
                )
            ) for eco in ("pypi", "npm")
        },
        "limitations": LIMITATIONS,
    }
    return sbom, summary


def generate(root: Path, output: Path) -> dict[str, object]:
    sbom, summary = build_inventory(root)
    data = (json.dumps(sbom, indent=2, sort_keys=True) + "\n").encode()
    summary["sbomSha256"] = sha256(data)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    output.with_suffix(".manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.root, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
