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

## Rollback / release record

For each promoted build retain the commit SHA, Vercel deployment ID/URL,
container image identifier, smoke output, CI statuses and known licensing
and calibration limitations. Deploy only a reviewed commit; roll back
through Vercel to an earlier verified deployment if any contract fails.

## Deployment incident / October 24, 2026

The repository is not a standalone FastAPI project for Vercel's automatic
FastAPI preset. Its deployable unit is the **one-image** `Dockerfile.vercel`
(with React UI, engine routes, immutable model evidence, and SBOM).

**Recorded incident:** Vercel projects `f1-prediction-engine-qriu` and
`f1-prediction-engine-xcif` used `framework=fastapi` even though the
repository has no Vercel-discoverable FastAPI entrypoint. Both repeatedly
returned `FASTAPI_ENTRYPOINT_NOT_FOUND`, including on CodeQL-only
Dependabot branch `fcfbb69`. That branch updated GitHub Actions metadata,
not the runtime entrypoint. Creating `app.py` would conceal the
misconfigured target and risk a partial service.

**Target policy, reviewed October 24, 2026:**

- `f1-pitwall-demo`: canonical integrated Container project.
- `f1-prediction-engine-qriu` and `f1-prediction-engine-xcif`:
  historical duplicates. Framework corrected to Container and Vercel's
  Ignored Build Step configured to **skip all builds**. Preview generation
  disabled. Retain their prior failed logs for incident evidence, but do
  not redeploy/reanimate these duplicates as separate FastAPI apps.
- `f1-prediction-engine-k469`, `f1-prediction-engine-n3sd` and
  `f1-prediction-engine-lqj9`: other duplicate Vercel projects formerly
  building the same Git commit. Automatic previews disabled and the ignored
  build step configured to skip all new builds; existing READY deployments
  and logs are left intact. No project was deleted or reassigned a domain.
- `f1-prediction-engine`: currently has no active deployment and is not
  the declared authoritative public game. Keep it unpromoted. Do not
  silently expand the production-release surface.

### Canonical Vercel project setting

After `scripts/vercel-ignore-build.sh` is in the reviewed default branch,
set **Project Settings → Git → Ignored Build Step** for
`f1-pitwall-demo` to:

```sh
sh scripts/vercel-ignore-build.sh
```

Vercel's convention is counterintuitive: **exit 0 skips**, **exit 1 builds**.
The rule skips `dependabot/*`, `renovate/*`, or a missing Git branch
identity, while preserving reviewed feature-branch previews and main
deployments. Dependabot changes still receive GitHub unit, TypeScript,
security, and container checks. Merging approved changes to `main`
triggers the canonical deployment as usual.

Test the skip contract before changing any Vercel project:

```bash
python3 -m unittest discover -s scripts/tests -p test_vercel_ignore_build.py -v
VERCEL_GIT_COMMIT_REF=dependabot/github_actions/example sh scripts/vercel-ignore-build.sh
# expected exit code 0 => skip
VERCEL_GIT_COMMIT_REF=main sh scripts/vercel-ignore-build.sh
# expected exit code 1 => build
```

The lightweight gate runs inside existing GitHub PR Validation; it does
not create a new scheduled job or poll for 15 minutes. The broader
per-commit deployment reporting proposed in PR #66 is a separate
observability feature and must avoid treating intentional skips as failures
or duplicating heavy CI checks.

### Release acceptance and prevention rules

1. **One authoritative target:** maintain the `f1-pitwall-demo` project
   ID, expected `framework=container`, and repository-root build in
   a reviewed target inventory. Avoid creating new Vercel projects when
   a connected canonical project already exists.
2. **Validate settings before deploy:** confirm Git repo, target team,
   configured framework, Dockerfile, ignore-build policy, and environment
   with authenticated project inspection; a successful `docker build`
   alone cannot validate Vercel project settings.
3. **Code-only bot branches:** test dependency changes in GitHub without
   spending Vercel build capacity on six related project connections.
   Never let `github_actions/**` changes create new FastAPI deployments.
4. **Separate CI and CD:** require scoped unit and integration results,
   dependency audit, evidence/SBOM checks, and one-image smoke before
   accepting a release. Production should remain the reviewed
   `main` version; neither CI nor Vercel previews auto-promote releases.
5. **Post-deploy evidence:** record deployment ID, exact source SHA,
   immutable image/dataset/SBOM IDs, UI + API smoke, response privacy,
   and actual edge TLS negotiation. Keep rollback instructions and a
   working previous deployment.
6. **Report drift, do not conceal:** if a project turns back to
   `framework=fastapi` or starts publishing a partial frontend-only
   copy, surface a deployment-configuration failure instead of adding
   a dummy FastAPI entrypoint or waiving failed CI checks.

**Verification limit:** correcting a project setting and skipping unwanted
previews stops new failures; it does not change the historical status of
previous ERROR deployments. A live preview can only be marked verified
after Vercel returns READY and an authenticated external UI/API smoke
succeeds. The canonical project's existing READY state is not proof of
unrestricted public access or an operational live MQTT subscription.
