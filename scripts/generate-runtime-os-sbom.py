#!/usr/bin/env python3
"""Generate and verify a CycloneDX OS-package inventory from built images.

Input dumps must come from the **final runtime containers** (not CI host or
builder stages). Every SBOM records its exact image IDs, Git commit, input
byte hashes and a manifest checksum. This is reproducible build evidence,
NOT a cryptographic signature, published registry digest, or complete SBOM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path

PKG_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+_.-]{0,180}$")
IMG_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
APK = re.compile(r"^(.+)-([0-9][A-Za-z0-9_.+~:-]*)$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def parse_dpkg(text: str) -> list[tuple[str, str]]:
    packages: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        pieces = line.split("\t")
        if len(pieces) != 2 or not PKG_NAME.fullmatch(pieces[0]) or not pieces[1]:
            raise ValueError("malformed dpkg-query installed package record")
        packages.append((pieces[0], pieces[1]))
    return checked(packages, "engine")


def parse_apk(text: str) -> list[tuple[str, str]]:
    packages: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = APK.fullmatch(line.strip())
        if match is None or not PKG_NAME.fullmatch(match[1]):
            raise ValueError("malformed apk installed package record")
        packages.append((match[1], match[2]))
    return checked(packages, "web")


def checked(packages: list[tuple[str, str]], image: str) -> list[tuple[str, str]]:
    if not packages or len(packages) > 10000:
        raise ValueError(f"{image} runtime package inventory missing or unreasonable")
    names = [x[0] for x in packages]
    if len(set(names)) != len(names):
        raise ValueError(f"{image} inventory contains duplicate packages")
    return sorted(packages)


def build(
    engine_bytes: bytes, web_bytes: bytes, *,
    engine_id: str, web_id: str, commit: str,
) -> tuple[dict[str, object], dict[str, object]]:
    if not IMG_ID.fullmatch(engine_id) or not IMG_ID.fullmatch(web_id):
        raise ValueError("runtime image IDs must be complete sha256:<64 hex> IDs")
    if not GIT_SHA.fullmatch(commit):
        raise ValueError("source commit must be a full 40-hex Git SHA")
    engine = parse_dpkg(engine_bytes.decode("utf-8"))
    web = parse_apk(web_bytes.decode("utf-8"))
    input_hashes = {
        "engine-dpkg-query": digest(engine_bytes),
        "web-apk-info": digest(web_bytes),
    }
    identity = {"sourceCommit": commit, "imageIds": {"engine": engine_id, "web": web_id},
                "sourceDigests": input_hashes}
    components: list[dict[str, object]] = []
    for name, os_type, pkg_list in (
        ("engine", "deb", engine), ("web", "apk", web),
    ):
        for pkg, version in pkg_list:
            purl = f"pkg:{os_type}/{pkg}@{version}"
            components.append({
                "type": "library",
                "bom-ref": f"{name}:{purl}",
                "name": pkg,
                "version": version,
                "purl": purl,
                "properties": [
                    {"name": "f1:runtimeImage", "value": name},
                    {"name": "f1:sourceImageId", "value": identity["imageIds"][name]},
                    {"name": "f1:inventoryMethod",
                     "value": "dpkg-query" if name == "engine" else "apk info -v"},
                ],
            })
    serial = uuid.uuid5(uuid.NAMESPACE_URL, "f1/runtime-sbom/" + digest(canonical(identity)))
    bom: dict[str, object] = {
        "bomFormat": "CycloneDX", "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}", "version": 1,
        "metadata": {"component": {
            "type": "application", "name": "f1-pitwall-final-runtime-images",
            "version": commit[:12],
        }},
        "components": components,
        "compositions": [{"aggregate": "incomplete"}],
        "properties": [
            {"name": "f1:sourceCommit", "value": commit},
            {"name": "f1:engineImageId", "value": engine_id},
            {"name": "f1:webImageId", "value": web_id},
        ],
    }
    manifest: dict[str, object] = {
        **identity, "specVersion": "1.6", "componentCount": len(components),
        "ecosystemCounts": {"deb": len(engine), "apk": len(web)},
        "limitations": [
            "Installed OS package inventory only for two locally built final container images",
            "Not an attested registry digest or signed image provenance",
            "Application Python/npm package inventory is a separate CycloneDX artifact",
            "Android and iOS native package dependencies are not included",
            "Container layers, binaries lacking package metadata, and external services are not enumerated",
            "No license clearance, vulnerability certification, or production approval implied",
        ],
    }
    manifest["sbomSha256"] = digest(canonical(bom) + b"\n")
    return bom, manifest


def generate(output: Path, engine_dump: Path, web_dump: Path, *,
             engine_id: str, web_id: str, commit: str) -> dict[str, object]:
    bom, manifest = build(
        engine_dump.read_bytes(), web_dump.read_bytes(),
        engine_id=engine_id, web_id=web_id, commit=commit,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical(bom) + b"\n")
    output.with_suffix(".manifest.json").write_bytes(canonical(manifest) + b"\n")
    return manifest


def verify(output: Path, engine_dump: Path, web_dump: Path) -> dict[str, object]:
    manifest_path = output.with_suffix(".manifest.json")
    try:
        old_manifest = json.loads(manifest_path.read_bytes())
        old_bom = output.read_bytes()
        if digest(old_bom) != old_manifest["sbomSha256"]:
            raise ValueError("runtime SBOM digest mismatch")
        rebuilt, manifest = build(
            engine_dump.read_bytes(), web_dump.read_bytes(),
            engine_id=old_manifest["imageIds"]["engine"],
            web_id=old_manifest["imageIds"]["web"],
            commit=old_manifest["sourceCommit"],
        )
        if old_bom != canonical(rebuilt) + b"\n" or manifest != old_manifest:
            raise ValueError("runtime SBOM or image identity drift")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("cannot verify runtime SBOM and its manifest") from exc
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-dump", required=True, type=Path)
    parser.add_argument("--web-dump", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--engine-image-id")
    parser.add_argument("--web-image-id")
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    if args.verify:
        manifest = verify(args.output, args.engine_dump, args.web_dump)
    else:
        if not all((args.engine_image_id, args.web_image_id, args.source_commit)):
            parser.error("image IDs and source commit required for generation")
        manifest = generate(
            args.output, args.engine_dump, args.web_dump,
            engine_id=args.engine_image_id, web_id=args.web_image_id,
            commit=args.source_commit,
        )
    print(json.dumps({
        "componentCount": manifest["componentCount"],
        "ecosystemCounts": manifest["ecosystemCounts"],
        "sbomSha256": manifest["sbomSha256"],
        "sourceCommit": manifest["sourceCommit"],
        "limitations": "Partial installed OS inventory, not release attestation",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
