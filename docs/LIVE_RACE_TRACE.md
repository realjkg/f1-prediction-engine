# In-race source capture and lap replay — Phase 1

**Status:** verified source-to-lap projection, reproducible conditional scenario,
immutable artifact loop, optional existing-engine pre-race model prior fusion,
paired accuracy scorer, read-only APIs, and Live Lab React screen are implemented
as a **research prototype**. No qualified in-race probability model, complete
automated provider spool-to-bundle service, live subscription, or verified
Singapore 2026 lap-25 checkpoint has been delivered. Never describe the
research output as a calibrated race-winner probability or live prediction.

## Transport choice

Use **MQTT over TLS** from OpenF1 to our private collector, not from the web
app. OpenF1's supposed WebSocket option is **MQTT-over-WebSocket**, so the
application-layer messages, topic names and broker semantics are identical.
The backend is the only holder of OpenF1 credentials. Do not expose tokens
in the browser or native app.

- Upstream endpoint: `mqtt.openf1.org:8883`, **native MQTT over TLS 1.3 or newer only**. The collector sets an SSL context minimum of TLS 1.3, verifies the public CA chain and broker hostname, and never enables `tls_insecure_set(True)`. **A TLS 1.2-only broker or runtime fails closed**, rather than triggering protocol downgrade or switching to WSS. OpenF1 documents MQTTS, but does not publish a guaranteed TLS 1.3 minimum. A real TLS 1.3 handshake and provider account test must be recorded before declaring compatibility.
- Permitlisted topics: `v1/position`, `v1/intervals`, `v1/laps`,
  `v1/pit`, `v1/stints`, `v1/race_control`, `v1/weather`.
- Subscriber QoS 0 minimizes overhead. Neither MQTT nor its QoS setting
  guarantees a complete historical trace when disconnections occur.
  Detect missing events and backfill using permitted historical REST access.
- Deployment boundary: require TLS 1.3 where supported at externally exposed HTTPS/WSS ingress too, with trusted certificates, hostname checks, short-lived app sessions, origin/authorization checks, and no plaintext fallback. The current container's localhost HTTP is a loopback-only development interface, **not a public TLS endpoint**. The app has no public TLS termination or live WSS endpoint configured in this phase.
- Later: a separate backend WebSocket broadcast can send validated state and
  model revisions to mobile/React. No reason to give each app client direct
  provider access or spend a subscription connection per device.
- MQTT source record fields `_id` and `_key` distinguish ingestion order
  and updates to the same document. Neither alone certifies a complete lap.
- Licensed real-time data is subscription-gated, so credentials and rights
  review are **required before using the live collector**.

Provider documentation: https://openf1.org/auth.html and
https://openf1.org/docs/ . Historical sessions from 2023 onward may be
available via the public REST API; review data rights and usage terms before
redistributing a dataset or using this in a commercial product.

## Data path

```text
OpenF1 MQTT/TLS feed (authorized backend session)
    -> topic-permitted, session-filtered raw event spool
       timestamp + provider _id/_key + SHA-256(raw bytes)
    -> cutoff-gated as-of lap projector (openf1_projection.py)
       positions + intervals + laps + stops + stints + control + weather
    -> LapCheckpoint schema (fail on missing leader, bad time or duplicates)
    -> append-only chained lap trace (SHA-256 integrity)
    -> GET /api/races/{raceId}/lap-trace?season=2026&lap=25
       observed running order only; forecastStatus = not-qualified
    -> bounded pace-conditional scenario (race_simulator.py)
       no-future-stops green-flag assumption, not calibrated
    -> frozen current-model prior research fusion (live_prior.py)
       explicit blend coefficient, no automatic promotion
    -> read-only API artifact + research-only Live Lab in React/Capacitor
```

The source-spool and checkpoint paths are deliberately separate. Assembling
a running order from messages observed at different times **can be wrong**,
especially during pit cycles and safety cars. The projector must establish
a reference lap boundary, verify each source field is from at/before that
cutoff, resolve MQTT document revisions (`_id`, `_key`), and refuse missing
coverage. Do not use race results or later timing to repair a live snapshot.

The SHA-256 chain is **tamper evidence**, not a publisher signature or an
authorization system. Additional signed supplier identity and access checks
are needed before promising authenticity or multi-tenant use. Only one
collector may write each trace file.

## Run the offline replay

A normalized checkpoint and its retained provider response are required.
Do not treat example data as an actual Singapore race state.

```bash
python3 scripts/ingest-lap-checkpoint.py \
  --checkpoint local/checkpoint-25.json \
  --source-payload local/provider-response-25.json \
  --trace data/live/singapore-2026.jsonl
```

The CLI confirms the declared source payload SHA-256, validates the complete
normalized checkpoint, and appends one chained evidence record. To expose
it in the FastAPI service, set `F1E_LAP_TRACE_PATH` to the resulting file
and restart. The API refuses missing or tampered traces; latest live views
also refuse stale data. Explicit past-lap replay remains accessible with
its true recorded timestamp.

### Optional licensed MQTT capture

Install vetted `paho-mqtt` in a **separate collector environment**; it is not
a production API dependency and no plaintext secrets belong in git. The
OpenF1 token must be obtained and refreshed securely through the supported
backend OAuth flow (an access token lasts about one hour).

```bash
export OPENF1_USER="<your-licensed-account>"
export OPENF1_ACCESS_TOKEN="<short-lived-access-token>"
python3 scripts/record-openf1-mqtt.py \
  --session-key <verified-session-key> \
  --rights-reference "<license-evidence-reference>" \
  --output data/live/provider-events.jsonl \
  --max-messages 10000
```

This collector requires TLS 1.3+ on the MQTT connection and rejects
missing TLS 1.3 support without downgrade. No live connection or verified
TLS 1.3 negotiation against the OpenF1 broker has been performed in CI.
It stores original source payload text, SHA-256, provider event
identity, and receive time. It never infers laps or writes win probabilities.
The optional collector is **not active** until a licensed account and the
optional dependency are provisioned. Logs never print tokens.

## Next acceptance steps for Issue #31

1. Obtain contractual permission and representative permitted OpenF1 session
   archive(s). Confirm all fields and provider event time semantics.
2. Write the as-of join/projector from the raw topic stream to fully qualified
   lap checkpoints, with regression tests for missing events, out-of-order
   updates, lap transitions, pit cycles and safety cars.
3. Replay a documented historic lap (for Singapore, a verified lap-25/62
   checkpoint if available) through the actual API and app, without assuming
   later results.
4. Train and compare in-race challengers against the **current running
   position** baseline on earlier events, calibrate on held-out historical
   races, then freeze forecasts prospectively.
5. Add a read-only live page using server-broadcast state. No provider token
   on the client. Show freshness, source provenance, lap number and data gaps.


## Experimental inference and accuracy artifact sequence

The source/observation/scenario/combined-prior path is implemented, but
**not** currently backed by qualified historic in-race training data.
The existing engine's older 2024 demo probability output cannot be
used as a genuine pre-race 2026 probability. `scripts/export-prerace-prior.py`
verifies a source ledger and refuses records not frozen before the race.
The driver-ID to race-number mapping and actual race start must come from
independent evidence and have complete coverage.

Retain raw permitted provider JSON, then prepare a single normalized
`{"session_key": N, "events": {"position": [...], "intervals": [...],
"laps": [...], "pit": [...], "race_control": [...], "weather": [...]}}`
object. Records must carry provider session keys, event timestamps and
driver numbers. Historical laps are included only after their completion.
For MQTT spools, each packet must retain its capture time, topic, provider
sequence/document key and exact SHA-256 payload. The projection will reject
missing full positions, lap-boundary disagreement, mismatched source times and
conflicting sessions. `driver_number` is a provider identity, **not** a
source-verified starter list; provide a separately verified entrant set.

Run a specific as-of lap with a **synthetic, licensed, or historically
permitted** source bundle:

```bash
python3 scripts/run-inrace-replay.py \
  --source /path/to/cutoff-sourced-openf1.json \
  --trace data/live/2026-singapore.jsonl \
  --artifacts data/live/artifacts \
  --race-id singapore --season 2026 --session-key <verified-key> \
  --lap 25 --total-laps 62 --as-of "<source-cutoff-with-timezone>" \
  --captured-at "<actual-capture-time-with-timezone>" \
  --entrants "<all-source-verified-driver-numbers>" \
  --source-type historical-archive
```

The run produces a hash-chained `LapTraceRecord` plus an immutable
`InRaceRunArtifact`. If observed gaps, green-flag conditions and three
validated complete laps per entrant are present, the conditional
`green-pace-no-stops-v1` scenario records deterministic trial frequencies.
Otherwise the artifact explicitly reports `insufficient-evidence`.
Scenario frequencies are **not calibrated win probabilities**.

An optional, independently frozen and timestamp-verified pre-race model
forecast can be passed to the replay with `--prior /path/to/prior.json
--scenario-weight 0.5`. The engine stores the original prior with the
`asof-prior-green-scenario-v1` blend and recalculates the entire result
when reading it through the API; it refuses changed prior or output bytes.
Never tune the weight against today's eventual race result.

Enable both read-only endpoints with
`F1E_LAP_TRACE_PATH=/path/to/trace.jsonl` and
`F1E_INRACE_ARTIFACT_DIR=/path/to/artifacts`:

- `GET /api/races/singapore/lap-scenario?season=2026&lap=25`
- `GET /api/races/singapore/lap-fusion?season=2026&lap=25`

Both endpoints show clear unavailable/invalid states. The frontend
**Live Lab** tab displays observed positions, green-pace scenario
frequencies and, if a matching frozen pre-race artifact exists, a side-by-side
model comparison. Default app operation continues on the pinned historical
demo with no current 2026 race data; the Live Lab must therefore show
unavailable unless the operator provides verified evidence and correct
runtime configuration.

`engine/f1engine/inrace_evaluation.py` scores each frozen checkpoint
against its *later published* finishing result using exact winner hit,
multiclass Brier and log loss. It compares frozen pre-race, currently
leading driver, green continuation and research fusion **on identical
entrant sets and as-of checkpoints**. This infrastructure measures accuracy
but does not yet establish an improvement. Model weights require training on
earlier races and evaluation on later, completely unseen races.

## Production communications gate

OpenF1 collector: authenticated MQTT/TLS 1.3, certificate validation,
hostname verification and downgrade refusal are implemented. The default
Compose stack is an isolated **localhost HTTP development/demo stack**
with plaintext web-to-engine Docker traffic. It is not presently compliant
with a universal TLS 1.3 network boundary. External HTTPS/WSS ingress and
backend mutual TLS require separate deployment wiring and verified
handshakes. No secure-production claim is made solely from HTTPS URLs in
the mobile build configuration.
