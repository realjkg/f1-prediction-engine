# Chronological in-race accuracy qualification

This is the follow-on to [LIVE_RACE_TRACE.md](LIVE_RACE_TRACE.md) and Issues #25 / #31.

**Status:** the scoring procedure and UI are implemented, but there is no
verified prospective live accuracy claim and no trained mid-race model promoted.
If the web app does not have an externally verified score report, it says so.

## What the engine tests

For exactly **one prespecified lap per historical Grand Prix**, compare:

| Paired candidate | What is measured |
| --- | --- |
| Frozen pre-race model | Existing engine P(winner) frozen before that race |
| Running-order baseline | The driver leading at the checkpoint, treated as the sole winner pick |
| Green-flag continuation | Unqualified deterministic no-stops lap-pace scenario |
| Walk-forward combination | Weight picked by proper scoring **earlier completed races only** |

The candidate weight grid is fixed at 0%, 10%, ..., 100% lap-scenario
weight. For each target event, the evaluator requires at least four other,
earlier races with outcomes **published before the target checkpoint**.
It selects the weight using multiclass Brier score, then winner log loss, then
the smaller scenario weight in a tie. The target's classified outcome is
only read after the weight has been selected and its prediction frozen.

Paired reported metrics: exact winner-hit rate, multiclass winner Brier
(lower is better), and winner log loss (lower is better). All candidates
score the exact same held-out events. One race contributes one score; using
hundreds of checkpoints from one race to inflate sample size is refused.

**Accuracy caveat:** Four historical training events is a *code minimum*,
not a claim of statistical adequacy. Real promotion requires a larger,
licensed, chronologically separate, prospective cohort and calibration,
with circuit, pit timing, safety car and tire effects validated against
the simple current-leader baseline.

## Artifact loop

1. `scripts/record-openf1-mqtt.py` captures permitted raw data over
   MQTT with certificate verification and TLS 1.3 minimum.
2. `scripts/bundle-openf1-spool.py` selects the source records available at
   a declared cutoff. Later events cannot be silently substituted.
3. `scripts/run-inrace-replay.py` turns those records into an immutable
   checkpoint, scenario, and optionally a pair of frozen pre-race prior/fusion
   artifacts. All files bind to the checkpoint's SHA-256.
4. Prepare an independently sourced, normalized classification JSON for
   each completed race. This must be a historically valid final result,
   with its **real publication timestamp**, and a separate retained provider
   source/rights audit. The digest prevents unnoticed changes to the
   normalized file but is not a provider signature.
5. `scripts/evaluate-frozen-inrace.py` verifies the trace chain, scenario,
   frozen prior and report digests and results-file hashes; it produces a
   deterministic, immutable aggregate accuracy report.
6. A configured read-only API `GET /api/inrace/accuracy` re-verifies
   the report digest on every request and returns a typed refusal on missing
   or modified evidence. The Live Lab page shows the paired results and
   prohibits describing them as production-calibrated predictions.

Sample evaluation input (paths are operator-provisioned files, not
repository fixtures):

```json
{
  "entries": [
    {
      "season": 2026,
      "raceId": "your-confirmed-race-slug",
      "lap": 25,
      "tracePath": "/secure/f1/race-trace.jsonl",
      "artifactRoot": "/secure/f1/artifacts",
      "resultSourcePath": "/secure/f1/verified-result.json",
      "resultSourceSha256": "64-lowercase-hex-characters-from-the-exact-result-file"
    }
  ]
}
```

Each normalized result file is a JSON object containing `season`,
`raceId`, `winnerDriverNumber` and a timezone-aware `publishedAt`.
The evaluator requires multiple races, one checkpoint per race, and at least
four earlier published independent results for a scored holdout. A single
Singapore example cannot establish accuracy. A manually normalized
classification requires a source-license and authenticity review.

```bash
python3 scripts/evaluate-frozen-inrace.py \
  --manifest /secure/f1/evaluation-manifest.json \
  --output /secure/f1/evaluation/forward-report.json

export F1E_INRACE_ACCURACY_REPORT=/secure/f1/evaluation/forward-report.json
# Restart the private engine API to expose read-only, integrity-checked results
```

A report is never overwritten. New cohorts get new artifact paths. This
prevents tuning earlier reported holdouts retroactively while retaining
research lineage.

## Hard blocks before production

- An active *authorized* telemetry subscription, proven TLS 1.3 negotiation,
  known session identity, complete entrant list and rights to redistribute.
- A real prospective pre-race model probability artifact frozen before the
  race, including grid changes and model/dataset source IDs.
- Reliable lap cuts that account for **pit cycles, lapped drivers, control
  changes, tire condition, telemetry loss and retirements**. The current
  pace scenario refuses missing conditions; it does not model race incidents.
- Event-stratified out-of-sample testing and confidence intervals across
  many races. No number of trials on one simulated lap substitutes for
  independently observed race outcomes.
- Separate security and model-governance sign-off for operating real-time
  inference. No auto-promotion or fallback to invented telemetry.
