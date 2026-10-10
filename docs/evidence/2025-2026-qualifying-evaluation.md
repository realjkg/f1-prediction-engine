# P0 accuracy evidence — current-event qualifying challengers

**Verified:** October 10, 2026. **Evaluation:** GitHub Actions run
[38093345263](https://github.com/realjkg/f1-prediction-engine/actions/runs/38093345263),
artifact `f1-2025-2026-verified-data` (ID `11685011529`), SHA-256 ZIP
`ea59985edead9ac91bcb5a75e8d71ad18ff1df5d44bfe1b5587cbbf105d3223e`.

Source: SHA-verified 2020–2024 reference plus the fetched full 2025 and partial
2026 (through 2026-10-10 UTC) historical dataset. The stored evidence includes
the SQLite warehouse and machine-readable `training/holdout-report.json`.

## Winner accuracy

| Model | 2025 (24 races) | 2026 (16 races) |
| --- | ---: | ---: |
| Rolling form | 29.2% | 6.3% |
| Logistic regression (prior rounds only) | 37.5% | 18.8% |
| GBM (prior rounds only) | 33.3% | 25.0% |
| Logistic + current qualifying | 54.2% | 50.0% |
| GBM + current qualifying | **66.7% (16/24)** | **68.8% (11/16)** |

## Proper scoring and placement diagnostics

Each Brier score sums squared error across the complete *race winner*
distribution; lower is better. Winner log loss is natural-log loss of the true
winner's predicted probability. Top-four recall measures how many actual P1–P4
drivers appear in the four highest-predicted top-four probabilities.

| Holdout | Model | Winner Brier ↓ | Winner log loss ↓ | Top-four recall ↑ | Top-pick ECE ↓ |
| --- | --- | ---: | ---: | ---: | ---: |
| 2025 | Logit baseline | 0.7657 | 1.6621 | 0.6458 | **0.0406** |
| 2025 | GBM baseline | 0.7785 | 1.7140 | 0.6667 | 0.0433 |
| 2025 | Logit + qual | 0.5990 | 1.1545 | **0.7917** | 0.1353 |
| 2025 | GBM + qual | **0.5321** | **1.0116** | 0.7812 | 0.2324 |
| 2026 | Logit baseline | 0.9019 | 2.2144 | 0.5312 | 0.1333 |
| 2026 | GBM baseline | 0.8458 | 1.9960 | 0.5312 | **0.1055** |
| 2026 | Logit + qual | 0.6378 | 1.3032 | **0.6250** | 0.0919 |
| 2026 | GBM + qual | **0.5211** | **1.1695** | **0.6250** | 0.1308 |

## Interpretation and limitations

The qualifying-conditional GBM wins on 2025 Brier score, and the same model
also wins on the untouched 2026 Brier score in this experiment. That is
encouraging across a major regulation change, but 24 and 16 events are small
samples. The top-pick expected calibration error is materially *worse* in
2025 despite gains in Brier/log loss and hit rate. Do not serve these outputs
as calibrated, production-ready probabilities.

Each round was predicted using labels strictly earlier than that round.
The *current-event* qualifying position, Q3 gap to pole and Q3 gap to
teammate were obtained from the independently stored qualifying table.
The predictor **never** reads the result table's `grid` or `position`
as same-race features. No special adjustment was made to force Bahrain's
Verstappen/Hamilton result.

This is a **retrospective post-qualifying replay**, not a verified pre-race
forecast. The source dataset does not preserve the timestamp when qualifying
became available, the authoritative final grid following penalties, or
historical meteorological forecast issue times. The historical entrant row
universe comes from the recorded results table; a true live system must use
a pre-race entry list instead. No pre-lights-out frozen forecast exists here.

## Next promotion gates (Issue #25 remains open)

1. Add an authoritative source-published-at/effective-at field per current
   qualifying, official starter and penalty, weather and tire input.
2. Freeze a complete input manifest, official grid, model digest,
   probabilities and prediction-cutoff time before the race.
3. Fit probability calibration *only* on eligible past seasons; test 2026
   (and later live predictions) without tuning calibration on those labels.
4. Promote a challenger to the containerized inference API/mobile interface
   only after the calibration and timestamp controls pass. Preserve and
   report the prior model as champion/control, and provide a rollback path.

**Decision:** Merge the reproducible feature and evaluation code. Do **not**
yet promote the qualifying challenger as a live model, despite the stronger
retrospective winner metrics.
