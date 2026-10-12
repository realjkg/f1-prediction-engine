# F1 Pit Wall — one-image demo deployment

## Deployment decision

**Use one OCI image for the demonstration.** The image includes the compiled
React PWA, Python FastAPI engine, immutable verified 2020–2024 race snapshot,
deterministic frozen prediction/backtest ledger, and CycloneDX lockfile
inventory. All UI and API requests share the same origin; there is no
externally routed frontend-to-backend connection or separate application
deployment. The React app uses hash routes, which work directly with a
static-files mount.

- **Single runtime process:** Python/Uvicorn runs FastAPI and serves compiled
  frontend assets via `f1engine.demo_site:create_unified_demo`.
- **Single release artifact:** `Dockerfile.vercel` works with Docker and the
  Vercel OCI function deployment feature introduced June 2026.
- **Frozen state:** historical prediction and SBOM artifacts are generated
  at image build time, verified at startup and during API reads.
- **No live-feed claim:** live MQTT collection, continuously written lap
  traces, independent prospective accuracy qualifications and live training
  require a stateful, continuously running private deployment. Vercel OCI
  Functions are **stateless** and may scale to zero. The Live Lab must
  continue showing typed refusals if there are no configured, verified
  live artifacts.
- **Security:** no OpenF1 credentials, collector processes or writeable
  model registries in the public demo. /metrics and interactive API docs
  are disabled by the unified demo wrapper; /api remains read-only.
- **Third-party rights:** current F1 data includes noncommercial-licensed
  sources. Review licensing before any revenue-generating or externally
  commercial demonstration.

## 1. One-image local build and test

```bash
docker build -f Dockerfile.vercel -t f1-pitwall-demo:local .
docker run --rm --read-only --tmpfs /tmp \
  --name f1-pitwall-demo -e VERCEL=1 \
  -p 127.0.0.1:8080:8080 f1-pitwall-demo:local
```

Browse http://127.0.0.1:8080/ and inspect `/api/config`,
`/api/evidence`, `/api/supply-chain` from the **same origin**.
`VERCEL=1` in the command explicitly emulates edge-managed TLS termination
and must **never** be used to expose a public plaintext service on a
standalone host. This is an HTTP-only loopback test.

## 2. TLS-1.3-only self-hosted container

To enforce a strict TLS 1.3 public edge, use a dedicated container host with
a trusted domain certificate and secure private-key mount:

```bash
docker run --rm --read-only --tmpfs /tmp \
  -v /secure/tls:/run/tls:ro \
  -e F1E_DEMO_TLS_CERT=/run/tls/server.crt \
  -e F1E_DEMO_TLS_KEY=/run/tls/server.key \
  -p 443:8080 f1-pitwall-demo:local
```

The Python server explicitly sets the OpenSSL minimum to TLS 1.3 and refuses
missing TLS material or support. This mode has no external network hops
between UI and API: the browser talks to one origin and one process.
Protect the host, certificate lifecycle, application access and containers
independently; review container SBOM attestations before release.

## 3. Vercel container preview (TLS policy limitation)

Vercel now supports `Dockerfile.vercel` as an OCI-compatible HTTP function.
Import `realjkg/f1-prediction-engine` into one Vercel project with the
repository root as project root. Let Vercel build `Dockerfile.vercel`.
The image listens on its injected `PORT`. Build and demo paths are immutable;
do not configure local live data paths, persistent source spools, OAuth
tokens or production-only inference.

**Blocking security deviation:** the Vercel-managed edge currently accepts
**TLS 1.2 and TLS 1.3**, and its published guidance says tenants cannot
disable TLS 1.2. Accordingly, **a Vercel public deployment is not a
verified TLS-1.3-only end-to-end release**. Hosting the OCI preview on Vercel
does not satisfy the previously approved no-downgrade requirement. Choose
the TLS-1.3-only self-hosted mode for strict enforcement, or obtain an
explicit change in security policy before using Vercel publicly.

Vercel docs:
- https://vercel.com/changelog/bring-your-dockerfile-to-vercel-functions
- https://vercel.com/kb/guide/does-vercel-support-docker-deployments
- https://vercel.com/docs/cdn

## 4. Release and artifact checklist

- [x] React and FastAPI bundled in the same image and HTTP origin
- [x] Historical training/backtest ledger generated from pinned data at build
- [x] Evidence hash chain and lockfile SBOM checked at startup
- [x] UI exposes Live Lab, provenance status and Inventory separately
- [x] Public app disables internal diagnostics and docs
- [ ] GH Actions unified-image build/start/route/security smoke is green
- [ ] Vercel project connected, actual image deployed and verified
- [ ] TLS-1.3-only public edge verified (Vercel cannot currently certify)
- [ ] Final image/native mobile SBOMs signed and verified
- [ ] Real OpenF1 MQTT account, live race source rights and durable collector
- [ ] Prospective trained and calibrated in-race model promoted after review

The items above have different release stages: a historical **demo** can
be presented independently of a production-calibrated **live predictor**.
No frozen historical race score proves current-race accuracy.
