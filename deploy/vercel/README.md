# Pit Wall — Vercel OCI endpoint scaffold

This directory is the operator runbook for PR #45. The image, UI, and API
already live together in the repository-root `Dockerfile.vercel`.
Vercel detects that filename, builds an OCI image and runs the HTTP server
on its injected `PORT`. Do not configure a second framework
build or a separate Vite site. No `vercel.json` rewrite is required.

## Deployment target

- Project name: `f1-pitwall-demo`
- GitHub source: `realjkg/f1-prediction-engine`
- Root directory: repository root, not `web/` or `engine/`
- Runtime preset: Container / `Dockerfile.vercel`
- Branch: review PR #45's feature branch as a preview first; promote a
  tested, reviewed main commit to production.
- Endpoint: use the **actual URL returned by Vercel**; do not assume a
  hostname or assert that it is publicly reachable before checking it.
- Health: `GET /healthz`; UI: `GET /`;
  API: `GET /api/config`, `/api/races`,
  `/api/evidence`, `/api/supply-chain`.
- Optional operator-only API: `POST /api/claude/brief`.
- Secrets must never be checked into Git or exposed through Vite variables.
  `AI_GATEWAY_API_KEY` and `F1E_DEMO_ACCESS_TOKEN`
  remain unset until operator access, billing limits and live-provider tests
  are approved. The Claude route fails closed without them.

## Public deployment gates

1. Review current dataset rights. The bundled historical dataset carries
   noncommercial third-party license restrictions. Do not present a public
   business demo as commercially licensed without written approval.
2. Run Python and web tests, dependency audit, the unified OCI build and
   single-origin HTTP smoke on the exact PR commit.
3. Link the intended Vercel account/team and project. Confirm GitHub repo,
   root directory and container preset. Keep preview deployment protection
   until the review and rights gates are cleared.
4. Once Vercel actually returns a URL, check the deployed container **over
   the network**, not only via local tests:

   ```bash
   python3 scripts/check-public-demo.py https://<actual-deployment-host>
   ```

   This smoke verifies TLS 1.3 **negotiation** with a trusted certificate
   and host, the React entrypoint, read-only engine routes, chain-backed
   evidence, the partial CycloneDX inventory, and blocked diagnostics and
   unauthenticated Claude calls. It does not prove that TLS 1.2 browser
   traffic is refused, and it does not enable Claude.
5. Inspect deployment logs, protect operations from abuse (rate limiting,
   spend controls and deployment protection), record build SHA and release
   evidence, and establish a rollback target before public promotion.

## Runtime boundaries

Browser to Vercel: HTTPS, TLS 1.3 preferred but Vercel-managed TLS 1.2
compatibility may remain. This is the explicitly accepted PR #45 boundary.

Vercel Function: single containerized read-only FastAPI + compiled React
app; immutable historical ledger and partial SBOM are baked into the image.
Nothing that relies on a permanent daemon, persistent filesystem, writeable
model registry or MQTT subscription belongs in this runtime.

AI Gateway: server-side credentials, operator authorization, fixed provider
host and CA/hostname-validated TLS 1.3 minimum. No gateway usage by default.

Live Lab: the image bakes in one **synthetic** race, `demo-synthetic`, built at
image build time by streaming invented messages through the real live-ingest
code (`scripts/build-demo-live-fixture.py`). The Live Lab opens on it
(`VITE_LIVE_LAB_RACE`, public build value) and every checkpoint is labeled
`synthetic-fixture`. It shows the screens and API; it is not provider data, a
real race, or a test of the broker connection.

Future live feeds: move a licensed MQTT/TLS 1.3 collector, durable event
stream, and prospective model calibration to a separate private, stateful
service. The public historical demo cannot claim current-race accuracy.

## Detecting broken or unexpected Vercel deployments

`deploy/vercel/projects.json` lists the Vercel projects that are meant to deploy
this repository (today only `f1-pitwall-demo`, a container build from
`Dockerfile.vercel`). On every push, `.github/workflows/vercel-deployment-check.yml`
runs `scripts/check-vercel-deployments.py`, which waits for each commit's
`Vercel – <project>` statuses and then:

- fails if an expected project failed or a status stayed pending;
- fails if a project that is not in the manifest is building the repository and
  failing (for example a FastAPI-preset project, which stops with
  `FASTAPI_ENTRYPOINT_NOT_FOUND` because this repository has no `app.py`-style entrypoint);
- warns when an unexpected project builds successfully, because it may publish a
  copy that is not the reviewed demo (for example a Vite-only frontend with no engine).

Optional: a `VERCEL_TOKEN` secret (and `VERCEL_TEAM_ID` variable for team projects)
adds Vercel's own error code and message to the report.

Owner action: the account also has `f1-prediction-engine-xcif` and
`f1-prediction-engine-qriu` (FastAPI preset, failing on every commit),
`f1-prediction-engine-k469` and `f1-prediction-engine-n3sd` (Vite preset,
frontend only) and `f1-prediction-engine-lqj9` (a second container build).
Disconnect the ones that are not wanted, or add them to the manifest with their
intended preset.

## Rollback / release record

For each promoted build retain the commit SHA, Vercel deployment ID/URL,
container image identifier, smoke output, CI statuses and known licensing
and calibration limitations. Deploy only a reviewed commit; roll back
through Vercel to an earlier verified deployment if any contract fails.
