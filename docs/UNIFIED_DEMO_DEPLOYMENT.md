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

**Updated transport policy for the demonstration (October 12, 2026):**
the browser-facing Vercel edge should **negotiate TLS 1.3 when the client
supports it**, but TLS 1.2 can be accepted by Vercel-managed ingress for
browser compatibility. Vercel controls edge TLS negotiation, not the React
application, so the app itself cannot force TLS 1.3. Its published policy
currently allows both TLS 1.2 and TLS 1.3. Do not describe a Vercel hostname
as TLS-1.3-only. The **separate backend OpenF1 MQTT collector and direct
AI Gateway outbound HTTPS client must enforce TLS 1.3 and refuse downgrade**;
the self-hosted ingress option remains TLS-1.3-only when that stronger
requirement applies. No sensitive tokens are included in frontend bundles.

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
- [ ] Browser-edge TLS 1.3 negotiation confirmed in deployed endpoint (TLS 1.2 edge compatibility permitted)
- [ ] Direct backend MQTT and AI Gateway TLS 1.3 handshakes verified using real accounts
- [ ] Final image/native mobile SBOMs signed and verified
- [ ] Real OpenF1 MQTT account, live race source rights and durable collector
- [ ] Prospective trained and calibrated in-race model promoted after review

The items above have different release stages: a historical **demo** can
be presented independently of a production-calibrated **live predictor**.
No frozen historical race score proves current-race accuracy.

## 5. Optional Claude historical evidence brief

The **Brief** tab includes an operator-only Claude panel. It is disabled
unless the following are set as **server-side protected environment variables**
in a Vercel project or on a self-hosted container:

- `F1E_CLAUDE_ENABLED=1`
- `AI_GATEWAY_API_KEY`: Vercel AI Gateway key held by the backend only
- `F1E_CLAUDE_MODEL=anthropic/claude-sonnet-5`
- `F1E_DEMO_ACCESS_TOKEN`: independent long random operator token, at least
  24 characters, issued and managed by the demo owner

Do not put either secret in `VITE_*` variables or store tokens in source.
The operator provides their access token in the UI only when invoking the
narrative, and the component clears it after the request. The key is never
sent to the browser. Use Vercel Deployment Protection and request limits
before opening access beyond trusted operators. The endpoint uses POST and
cannot alter race models or ledgers. It returns a text-only commentary bound
to the selected frozen prediction's record SHA-256; race classifications and
live telemetry are not supplied to Claude. The outbound gateway connection
requires TLS 1.3, with certificate and hostname verification.

**Research disclaimer:** a Claude brief does not improve race prediction
accuracy. Models remain the existing statistical engine. The current Vercel
OCI demo is historical replay only, with no durable live MQTT subscriber.
Enable this panel only after operator access controls, key management,
model cost limits, and a real authenticated AI Gateway smoke test succeed.
