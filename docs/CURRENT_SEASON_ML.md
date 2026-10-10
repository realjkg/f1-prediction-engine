# Current-season ML data and evaluation

## Coverage, as checked October 10, 2026

The original 2020–2024 snapshot remains immutable. The separate current-season
artifact is made with a UTC **exclusive** as-of date of 2026-10-11:

- 2025: 24 completed Grand Prix rounds and their result and qualifying rows.
- 2026: 23 races on the schedule, 16 completed Grand Prix rounds; the seven
  remaining races have **no race-result labels** in the store.
- 2026 Bahrain Grand Prix in Malaysia: venue is Sepang (`circuit_id=sepang`),
  not Sakhir. Circuit identity and race branding are different fields.
- The refresh also preserves recorded sprint results; qualifying and sprint
  sessions held before an upcoming race can be added once the upstream source
  publishes them.

The CI artifact includes Parquet tables, `provenance.json` with the table SHA-256
hashes, `DATASET_VERSION`, a licensed-source notice, the SQLite training store,
and the chronological benchmark report. Artifacts expire after 14 days; the
workflow runs weekly after merging to keep the generated artifact fresh. Its
existence alone does **not** release any new model into the browser demo.

## Rebuild locally

From the repository root, install the engine:

```bash
python3 -m pip install --require-hashes -r engine/requirements.lock.txt
python3 scripts/refresh-data.py \
  --seasons 2025-2026 \
  --as-of 2026-10-11 \
  --dataset-id 2025-2026-through-2026-10-11 \
  --data-dir data/snapshot-2025-2026
python3 scripts/build-training-store.py \
  --snapshot data/snapshot \
  --snapshot data/snapshot-2025-2026 \
  --as-of 2026-10-11
python3 scripts/benchmark-training-store.py --season 2025 --season 2026
```

The cutoff is exclusive for race results because the Jolpica snapshot records
only a date, not the exact time the result became final. Do not infer same-day
availability. Race schedules may be known ahead of time, but outcomes must not
appear in training until their date precedes the cutoff.

## What the database does

SQLite is the simple, portable feature store for the existing ARM64 laptop.
It records each race's season, round, **actual circuit**, completed results,
qualifying, sprint results, source dataset hash, and training features.
`training_samples` holds the eight current, no-lookahead historical features
and whether a driver won, reached the podium, or finished top four.
`training_rows_before(season, round)` excludes the target race and all
subsequent rounds. Store builds refuse overlapping seasons and outcome labels
at or beyond the selected cutoff.

Run `benchmark-training-store.py` to train two distinct SQL-fed challenger
models (logistic regression and gradient-boosted trees), plus a rolling-form
baseline. Their winner-hit rate, multiclass Brier loss, and top-four recall
are measured with a fresh fit for each target round using only earlier labels.
The models in the shipped web app have **not** been replaced with these
challengers; promotion needs evidence on held-out races.

## Next accuracy gates

1. **Verified pre-race inputs:** model the *current round's* official grid,
   qualifying gaps, confirmed starters, venue and weather forecast as of
   prediction time. The existing production feature vector uses historical
   qualifying form, not the current grid. Record publication timestamps.
2. **2026 technical reset:** measure the change in car and team performance
   under the 2026 regulations, emphasize recent form only if out-of-sample
   evaluation supports doing so, and distinguish wet/dry track conditions.
3. **Richer session telemetry:** evaluate licensed practice long-run pace,
   tyre degradation, reliability and pit-stop patterns. The OpenF1 weather
   source is declared but **not ingested** by this release.
4. **Proper calibration:** use chronological 2025 to select the model or
   ensemble weights; use 2026 as a later, untouched evaluation set.
   Report winner Brier/log loss and top-four calibration, not just hit rate.
5. **Release discipline:** preserve the 2024 deterministic reference,
   produce signed versioned evaluation artifacts, check drift and data gaps,
   and only then expose new probabilities in the Pit Wall UI.

## Limits

A database makes retrieval, replay, historical feature materialization, and
version control more reliable. It does not automatically make any prediction
more accurate. No synthetic results, forced Verstappen/Hamilton outcomes,
cross-race target leakage, or automatic online model promotion are permitted.
Historical source-data licenses currently include non-commercial terms;
resolve usage rights before a customer-facing commercial deployment.
