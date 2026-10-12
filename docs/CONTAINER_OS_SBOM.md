# Final-container OS inventory — build evidence

The existing CycloneDX 1.6 source-lock inventory covers Python and npm. The new Docker
CI artifact inventories installed Debian packages in the final Python engine image
and installed Alpine packages in the final Nginx web image.

## Evidence in the workflow

The container smoke job extracts installed package lists by running dpkg-query and
apk info -v inside the final images with networking disabled. It exports one
additional artifact called **f1-final-container-os-sbom** containing:

- f1-container-os.cdx.json: CycloneDX 1.6 final-image OS packages and image IDs
- f1-container-os.cdx.manifest.json: BOM hash, two image IDs, source Git SHA,
  package totals, and hashes of the exact installed-package source records
- engine-dpkg.tsv and web-apk.txt: retained raw package inventory evidence

scripts/generate-runtime-os-sbom.py --verify independently regenerates the BOM
from the saved sources and rejects changes, missing packages and inconsistent
hashes. Tests also cover duplicate records and malformed image identifiers.

The package list is deliberately not exposed on a public app endpoint. The
Inventory screen continues to display only the independently verified
application lockfile SBOM, with a separate release gate for this CI evidence.

## Limitations and release gates

A local Docker image content ID is **not** a signed registry image digest.
This OS inventory and the source-lock SBOM remain **incomplete**: signed image
provenance, non-package-managed binaries, Android and iOS native dependencies,
container layers, external services, license checks and actual deployment
attestation are not included.

Before release, independently verify that the same Git SHA, built image IDs
and artifact are tied to the published container images. Produce signed OCI
and native app supply-chain attestations; perform vulnerability and licensing
review. Do not claim live-forecast readiness without independently verified
source coverage, prospective calibration, real TLS 1.3 connections and
authorized OpenF1 data rights.
