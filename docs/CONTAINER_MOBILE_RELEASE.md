# Container-first F1 Pit Wall and mobile release process

## System of record

The backend is deployed as a containerized FastAPI service. Nginx serves the
compiled React PWA and proxies `/api` to the private engine Docker network.
The model/data refresh runs as a **separate** Docker Compose training job and
stores its validated outputs in a named volume. Mobile releases are Capacitor
packages from the same React source; they connect to a public HTTPS API ingress
to this service. **An iPhone does not run the Dockerized Python server.**

The current engine container deliberately replays the existing 2020–2024
reference set on startup and serves its deterministic 2024 evidence. The
new 2025/2026 SQLite features are challengers, not yet promoted predictions.
Do not advertise the mobile UI as current-season predictions until the
model promotion gate is complete.

## Start on ARM64 or x86_64

```bash
docker compose build engine web
docker compose up -d engine web
docker compose ps
curl --fail http://127.0.0.1:8080/api/config
```

Open `http://127.0.0.1:8080` for the local, production-built container UI.
This is **not** a Vite dev deployment. Configure a TLS-enabled ingress with
a real domain before mobile use; the local port is bound only to loopback.
Expose the UI's `/api` reverse-proxy path, not the private engine container.
Do not expose `/metrics` to the internet. Protect any public deployment with
an appropriate authentication and access-control gateway.

```bash
F1E_AS_OF=2026-10-11 docker compose --profile training run --rm trainer
```

The training job independently refreshes 2025 and partial 2026 results,
builds SQLite features, and calculates walk-forward benchmarks. Its outputs
are stored in the `training` Docker volume. It does not silently replace the
running baseline; model promotion is a separate reviewed operation.

## Android

Set your publicly reachable TLS backend origin (the host serving `/api`).
It must be an HTTPS hostname; localhost and development host fallbacks are
blocked during mobile builds.

```bash
cd web
export VITE_F1E_API_BASE_URL=https://f1-api.example.org
npm ci
npm run build:mobile
cd android && ./gradlew assembleDebug
```

Use the same codebase to build a debug APK fully inside Docker on ARM64/AMD64
Linux hosts, without installing Android SDK locally:

```bash
docker build --platform linux/amd64 \
  --build-arg VITE_F1E_API_BASE_URL=https://f1-api.example.org \
  -f deploy/Dockerfile.android --output type=local,dest=./dist-mobile .
```

The exported `dist-mobile/f1-pitwall-debug.apk` is a DEBUG build. Play Store
distribution additionally requires release signing, version increments,
app icons, privacy disclosures and store verification. Do not put signing
keys or API tokens in build args, images or client bundles.

## iOS

Use macOS with Xcode, Node 24 and CocoaPods:

```bash
cd web
export VITE_F1E_API_BASE_URL=https://f1-api.example.org
npm ci
npm run build:mobile
npx cap open ios
```

Select your Apple team, set the correct bundle identifier, sign the
Release scheme, archive in Xcode and distribute through TestFlight/App Store
Connect. Apple signing credentials must remain in macOS Keychain or trusted
CI secrets. There is no supported Linux-Docker replacement for Xcode.

## Reliability and accuracy gates

- Produce evidence-bound 2025/2026 snapshot hashes, SQLite tables and holdout
  reports. Do not substitute predictions with actual known results.
- Keep immutable source snapshots; evaluate model challengers chronologically.
  Only roll forward an evidence-backed model whose out-of-sample Brier score,
  calibration, winner hit rate and top-four recall improve.
- Evaluate XGBoost/LightGBM/CatBoost as **optional** tabular challengers only
  after reproducible builds and licensing checks. Evaluate private Qwen/Mistral
  for explainable race briefs or feature extraction, not as an unproven numeric
  probability oracle. LLM-generated facts are never allowed as labels.
- Supply live/current qualifying, confirmed grid, weather forecast, tyre and
  practice session data with publication timestamps; only data available
  before the prediction cutoff may enter feature generation.
- Add mobile contract smoke tests against a TLS API and upgrade handling
  before external distribution. `build:mobile` fails without an explicit
  HTTPS backend, preventing a misleading disconnected mobile package.
