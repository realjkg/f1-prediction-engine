# F1 Pit Wall — release qualification ledger

**As of October 11, 2026.** Engineering freeze candidate, **NOT** a production
live-prediction release. Scope: informational F1 application (web/PWA,
Capacitor/iOS/Android), FastAPI ML engine, MQTT race-state capture, secure
Docker deployment, immutable lap and model-evaluation artifacts.

This ledger is intentionally specific about the difference between code
existing, a synthetic test passing, an operational service being provisioned,
and model accuracy being independently established. A green test suite does
not override a missing provider license or a statistically inadequate
prospective evaluation.

## Evidence inventory

| Artifact/capability | Actual implementation | Evidence/state |
| --- | --- | --- |
| Existing pre-race model and chronological challenger search | `engine/f1engine/store_benchmark.py`, `model_search.py`, `training_store.py`; `scripts/search-f1-challengers.py` | Historical 2025/2026 **research**, not timestamp-proven live accuracy; promotion blocked (#25) |
| Authorized backend MQTT capture and live per-lap ingest | `scripts/record-openf1-mqtt.py`, `scripts/run-live-ingest.py` | Broker/topic validation, server-only credentials and TLS 1.3; **real licensed broker connection unverified** |
| Source-to-lap reconstruction | `scripts/bundle-openf1-spool.py`, `engine/f1engine/openf1_projection.py` | Cutoff-bounded replay with missing/late input refusals; real lap-25/62 Singapore source **not archived/verified** |
| Immutable observation trace | `engine/f1engine/lap_trace.py`, `scripts/run-inrace-replay.py` | Source hashes and chained checkpoints; hashes prove integrity, **not independent provider authenticity** |
| Conditional simulated continuation | `engine/f1engine/race_simulator.py`, `inrace_pipeline.py` | Experimental green-flag/no-more-stops scenario; not calibrated for pits, tire wear, cautions, incidents or retirements |
| Pre-race prior + in-race research combination | `engine/f1engine/live_prior.py`, `scripts/export-prerace-prior.py` | Frozen evidence binding; no automated model promotion |
| Chronological paired accuracy | `engine/f1engine/inrace_walkforward.py`, `inrace_evaluation.py`, `scripts/evaluate-frozen-inrace.py` | Compares previous-model prior, leader baseline, scenario and walk-forward mixture; no real prospective published race cohort established |
| Read-only app APIs | `engine/f1engine/app.py` | `/api/races/{raceId}/lap-trace`, `/lap-scenario`, `/lap-fusion`, `/api/inrace/accuracy`; typed error when source is absent |
| Actual app screens | `web/src/routes/LiveLabPage.tsx`, `SupplyChainPage.tsx` | Research labels, observed vs projected distinctions, full lockfile inventory with search and release gates; browser and Capacitor share UI |
| TLS 1.3 transport | `compose.tls.yaml`, `scripts/serve-tls13.py`, `deploy/nginx-tls.conf`, MQTT collector | Synthetic certificate smoke passed; real public domain, certificate chain and provider handshake pending |
| Dependency inventory SBOM | `scripts/generate-sbom.py`, `engine/f1engine/supply_chain.py`, `deploy/Dockerfile.engine` | Deterministic **CycloneDX 1.6 partial inventory** embedded in runtime image; source locks validated on each read |
| Source-lock SBOM display | `GET /api/supply-chain` plus Inventory tab | `status=lockfile-inventory-only`, `releaseReady=false`; runtime smoke validates API response over localhost and TLS 1.3 |
| Web, engine and native build | Python/React CI, Docker Compose and mobile smoke | Last reviewed green CI: see below. Signed mobile-store release and actual endpoint testing remain separate |

### Precise SBOM contents

From `engine/requirements.lock.txt`, `engine/requirements-dev.lock.txt`,
and `web/package-lock.json` on the reviewed `main` commit:

- **281 total pinned package records:** 32 Python and 249 npm entries.
- Python: 23 runtime pins and 9 additional development pins.
- npm entries are versioned lockfile paths, not deduplicated package identities.
- Examples in the lockfiles: FastAPI 0.143.0, Pydantic 2.14.0,
  scikit-learn 1.7.2, React 19.3.0, Vite 8.3.4,
  `@capacitor/core` 8.5.3.
- CycloneDX composition status: **incomplete**. No claim that operating
  system libraries, Android/iOS native frameworks, runtime image layers,
  license clearance or signed provenance are covered.
- The `SBOM_UNAVAILABLE` and `SBOM_INVALID` API responses are **release
  blockers**, never triggers for a synthetic display fallback.

CI SBOM artifact: [2026-10-11 release inventory run](https://github.com/realjkg/f1-prediction-engine/actions/runs/38171913344),
artifact `f1-cyclonedx-lockfile-inventory`. This is a GitHub Actions
archive containing the JSON BOM and integrity manifest, not a complete
signed software supply chain.

### Tested build reference

The last inspected baseline was `30df4a52855f8dd562d1e002124403b41e3f3d53`
on `main`. Do not represent that SHA's results as passing for later commits;
each proposed release SHA requires its own verification.

- [PR validation and SBOM job passed](https://github.com/realjkg/f1-prediction-engine/actions/runs/38171913344)
- [CodeQL passed](https://github.com/realjkg/f1-prediction-engine/actions/runs/38171715857)
- [Docker Compose smoke passed](https://github.com/realjkg/f1-prediction-engine/actions/runs/38171715810)
- [Native mobile build smoke passed](https://github.com/realjkg/f1-prediction-engine/actions/runs/38171715782)
- [TLS 1.3/mTLS synthetic integration smoke passed](https://github.com/realjkg/f1-prediction-engine/actions/runs/38160805921)

The latter four checks were performed on their stated earlier heads, not
the new release candidate. Review exact SHA, source tree, and CI outcomes
together before release.

## Production release checklist

| Gate | State | Acceptance evidence still required |
| --- | --- | --- |
| [x] Source model inference and historic ML baselines | Implemented | Keep 2024 demonstration separate from 2026 research |
| [x] Raw MQTT ingest code, live per-lap ingest, event cutoff and trace hashing | Implemented/tested offline with a synthetic stream | Authorized license and real live provider connection |
| [x] Research model-combination code and immutable evaluator | Implemented/tested offline | Real independent training and held-out race outcome archives |
| [x] Web Live Lab and searchable Inventory screen | Implemented | Signed deployed app smoke and real user acceptance |
| [x] Partial reproducible lockfile SBOM in runtime image | Implemented | Container/native installed-software scans and signed artifacts |
| [x] TLS 1.3/mTLS Compose smoke | Implemented | Production public endpoint and authenticated OpenF1 handshake |
| [ ] Commercial telemetry rights and allowed redistribution | **External blocker** | Licensed stream authorization, data-use and retention conditions |
| [ ] 2026 Singapore lap checkpoint provenance | **External blocker** | Real session ID, field roster, source data with timing metadata |
| [ ] Live operation reliability | **Blocked** | Gap backfill, duplicate/out-of-order handling, source disconnect recovery, health alarms, replay after restart |
| [ ] Model accuracy/calibration against sufficient unseen races | **Blocked** | Verified forward-frozen predictions, proper scores, confidence intervals, improvement over current leader, subgroup tests |
| [ ] Full deployed software provenance | **Blocked** | OS and native package SBOM, signatures, image digests, vulnerability review, reproducible build attestation |
| [ ] Production operations | **Blocked** | Public TLS 1.3 verification, key rotation, service monitoring, error budgets, rollback drill |
| [ ] Distribution approvals | **Blocked** | Platform signing, legal/privacy/store reviews and operator go/no-go |

**Gate rule:** A release may show a clearly marked research demonstration
only. It must not claim live accuracy, real-time coverage, approved commercial
data rights, or a production-qualified F1 winner model until every applicable
external and empirical gate has written evidence.

## Next executable actions

1. Configure licensed provider data collection in a private service. Test
   authenticated TLS 1.3 negotiation and continuity across an entire real
   event, recording source events with capture times.
2. Replay multiple previously unseen full historic events with authenticated
   source archives and frozen cutoff times, including pits, caution periods,
   retirements and incomplete feeds.
3. Run `scripts/evaluate-frozen-inrace.py` on the independently verified
   cohort. Require correct event-level baseline comparisons, Brier, log loss,
   calibration and confidence bounds, then review a candidate revision
   manually.
4. Collect OS/container and Android/iOS native SBOMs from actual release
   binaries, sign provenance tied to the deployment SHA, and perform disaster
   recovery/rollback and real-TLS handshakes.
5. Only then assess activation of a true live forecast UI. Until qualification,
   the Live Lab must keep the experimental advisory label.

Keep Issues [#25](https://github.com/realjkg/f1-prediction-engine/issues/25)
and [#31](https://github.com/realjkg/f1-prediction-engine/issues/31)
open for the empirical and operational blockers. No empty-checkbox closure
based solely on green synthetic CI.
