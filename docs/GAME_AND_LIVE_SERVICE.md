# F1 Pit Wall: operational game and licensed live data wiring

## What is actually usable

The **Grand Prix Challenge** is a free, points-only race-history game. The
Start Challenge button opens a completed historic round, lets the player
choose a three-driver podium, runs the existing 30-second timer, and asks the
server to score every pick against the result and four model competitors.
Persistent local progress, a streak, badge awards, and a model leaderboard
are already implemented. There are no monetary stakes or prizes.

The **OpenF1 live engine** is a separate, private runtime. It does not run in
a Vercel OCI Function. An isolated background container, when provisioned
with an authorized OpenF1 account and recorded rights, subscribes to
`mqtt.openf1.org:8883` using TLS 1.3 minimum. Existing ingest code writes:
- a source-preserving durable message spool;
- verified, hash-chained lap checkpoints when coverage is sufficient;
- experimental per-lap green-pace scenario artifacts;
- optional provenance-bound fusion against a properly frozen pre-race prior;
- a heartbeat reporting broker state and most recent accepted message time.

A JSON read contract is now available via
`GET /api/live/status?season=2026&race_id=<verified-race-slug>`.
Only fresh MQTT connection evidence with recently accepted source messages
can return `feedState=connected`. A recently computed scenario can return
`inferenceState=conditional-research`. **Neither means that calibrated
production outcome probabilities are available.**

## Start the private live service

Prerequisites:
1. Contractually permitted OpenF1 live access, including clear public
   redistribution rights for the fields being served, if applicable.
2. Verified season, race slug, actual session key, full entrant list and
   race distance. Do **not** invent these values.
3. A long-lived Docker host with persisted volumes and externally provisioned
   TLS 1.3 server/client certificates for `compose.tls.yaml`.
4. A secret file on that host containing the licensed provider password,
   readable by the Docker runtime but excluded from Git and artifacts.
5. Verified, reviewed `paho-mqtt==2.1.0` dependency provenance and SBOM.
   The collector image's optional paho layer is version-pinned but **not
   hash-locked** yet; this is an outstanding release-hardening gate.

Set the following environment variables in the **private host** (not in a
Vite/browser bundle or GitHub issue):

```text
F1E_TLS_CERTS_DIR=<private TLS cert directory>
F1E_OPENF1_PASSWORD_FILE=<path to host-mounted provider password secret>
OPENF1_USER=<licensed account username>
F1E_OPENF1_RIGHTS_REF=<internal approved rights/license reference>
F1E_LIVE_SESSION_KEY=<provider-verified session key>
F1E_LIVE_SEASON=<actual race year>
F1E_LIVE_RACE_ID=<verified slug>
F1E_LIVE_TOTAL_LAPS=<actual race distance>
F1E_LIVE_ENTRANTS=<comma-separated verified full roster>
```

Start the secure overlay:

```bash
docker compose -f compose.tls.yaml -f compose.live.yaml config --quiet
docker compose -f compose.tls.yaml -f compose.live.yaml up -d --build
```

Only the TLS web ingress in `compose.tls.yaml` binds a host port (default
loopback 8443). The MQTT subscriber has no inbound port. The engine and
collector share a durable named `live` volume; the engine mounts it
read-only. A verified pre-race prior is optional and must be independently
frozen before its first target lap.

The frontend's Vercel production project remains **historical-only** until
it can securely reach this distinct TLS-protected backend (via a reviewed,
authenticated server relay or approved read-only HTTPS origin). Do not point
the browser at the MQTT broker or embed an access token in JavaScript.

## Release checklist

- [x] Engine-scored free game loop, browser-local game progress and AI rivals
- [x] Start Challenge entry point and game instructions
- [x] Collector MQTT/TLS 1.3 source validation + deterministic research simulation
- [x] Durable collector heartbeat and truthful status API
- [x] Private Docker Compose collector/engine volume wiring
- [ ] Licensed OpenF1 account, scope, redistribution permission, secret provisioned
- [ ] Verify a real OpenF1 TLS 1.3 handshake and subscription on the target host
- [ ] Verified race/session identity, source completeness and active lap emissions
- [ ] Public read relay from Vercel to private backend with authorization
- [ ] Out-of-sample prospective calibration before calling output live probabilities
- [ ] Collector container dependency attestation, SBOM and vulnerability checks
- [ ] Build, UI, integration tests and production smoke on the exact release commit
- [ ] Vercel deployment after build quota is available

**Never present animated cars as observed position/telemetry.** CSS motion is
decorative. Only the verified lap trace can tell the UI a running position.
No live inference or video is active merely because the UI is deployed.

OpenF1 docs: https://openf1.org/auth.html
