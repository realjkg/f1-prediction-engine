# F1 Pit Wall — live interaction and inference release plan

Status: **not deployed in the public Vercel demo**. The current production image
contains a historical 2020–2024 snapshot, fixed pre-race evidence, podium
game scoring, and a read-only checkpoint reader. An animation is **visual
only**, not live car location data.

## Current observable capabilities

| Experience | Source | Runtime status |
| --- | --- | --- |
| Race Rewind predictions, podium picks, scoring, badges | Immutable historical snapshot and ledger | Implemented |
| Animated race straight and speed/pause controls | Original CSS/SVG artwork, not telemetry | Implemented on this PR |
| In-race Lab checkpoint and scenario explorer | Verified stored lap trace and conditional scenario artifacts | Implemented; returns typed refusal when absent |
| Current 2026 session timing and car position | Licensed OpenF1 MQTT over TLS | **Not connected to public Vercel demo** |
| Continuous inference and qualified win probabilities | Stateful private collector + inference worker + model registry | **Not operational for public demo** |
| Active session freshness/health | Signed heartbeat from collector | **Not implemented** |

The 15-second Live Lab refresh asks HTTP for newly stored evidence. It **does
not** create a source connection or run the model. A stored artifact with
sourceType `licensed-live` proves only historical provenance, **not** active
feed connectivity.

## Architecture to implement

1. A continuously running, privately hosted collector authenticates to a
   properly licensed OpenF1 MQTT broker on port 8883 with TLS 1.3 (refuse
   downgrade) and consumes authorized sessions/laps/intervals/positions/weather
   and race control. Use strict session identity and message validation;
   credentials must never reach the browser or OCI demo.
2. Normalize observations into an append-only durable stream. Bind every
   observation to `season`, `race_id`, `session_key`, `lap`,
   `source_time_utc`, `ingested_at_utc`, and source digest. Reject out-of-order
   revisions without discarding the original or its provenance.
3. An independent inference worker consumes complete lap checkpoints,
   obtains an as-of model frozen **before** the target race result, and produces
   an immutable, hashed prediction record. Train/qualify out of the serving
   path; a restart must never rewrite already published inference.
4. Write immutable, signed or hash-chained checkpoint + model evidence
   to a durable private store. Expose a least-privilege read API with
   `GET /api/live/status`, `GET /api/live/sessions`,
   `GET /api/live/sessions/{session_key}/latest`, and
   `GET /api/live/sessions/{session_key}/events` (these routes are **planned**,
   not deployed). Serve only source-licensed fields.
5. From Vercel, the browser retrieves the signed/latest checkpoint using
   a read-only HTTPS interface. Add event delivery via authenticated SSE or
   WebSocket only when the stateful service and access controls are ready.
   Public HTTPS at Vercel edge must not be represented as strictly TLS-1.3-only
   until independently verified; the existing design records this deviation.
6. Make the UI show source state (`offline/stale/live`), last update time,
   lap count, actual source type, model revision and freshness, and separate
   verified timing positions from forecast outputs. No smoothing, animation,
   or interpolation may be described as observed if not directly sourced.
7. Include a Race Rewind offline fallback; never invent live lap times,
   overtakes, car positions or probabilities when source / qualification fails.

## Live release acceptance gates

- [ ] OpenF1 or another permitted source subscription and publication rights approved.
- [ ] Private, long-running container host and persistent storage provisioned.
- [ ] MQTT/TLS1.3 validated end-to-end; tokens in a secret manager and rotated.
- [ ] Session mapping, schema, deduplication, freshness and reconnection tests.
- [ ] Real checksum-bound lap records and deterministic model outputs generated.
- [ ] Out-of-sample forward accuracy, calibration and baseline comparisons accepted.
- [ ] Minimum sample size, model provenance, SBOM, signing and reproducibility gates pass.
- [ ] Source heartbeat, stale/degraded/outage UX and telemetry watchdog implemented.
- [ ] No-source case returns an explicit unavailable state with zero invented data.
- [ ] Verified production public endpoint, mobile access, CSP, rate limits and access policy.

Provider reference: https://openf1.org/auth.html (authenticated MQTT over TLS;
public historical REST is not a substitute for a current live stream).

The app's game has no wagering, entry fee, financial prize or outcome purchase.
Scoring belongs to the historical, already-completed Race Rewind mode.
