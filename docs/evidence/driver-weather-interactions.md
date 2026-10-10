# Driver progression, experience, reliability and weather research

## Features compared under the same race cohort

The verified 2020–2024, full 2025 and completed 2026 SQLite dataset supports:

| Challenger | Predictors | Research question |
| --- | --- | --- |
| `pole` | This event's qualifying position | How much does a simple pole baseline explain? |
| `gbm-qual`, `logit-qual` | Prior form, same-event qualifying and lap gaps | Value added beyond pole |
| `gbm-dyn-qual`, `logit-dyn-qual` | Above plus prior driver/team experience and progress | Does longitudinal ability add accuracy? |

The eight new pre-race dynamics variables are prior sample starts, current-season sample starts, previous-eight driver classified finish rate, previous-16 constructor classified rate, recent top-four frequency, recent finish-position improvement, recent qualifying improvement, and positions gained from qualifying in recent completed races. Trends compare the latest three available historical results against an earlier group. Missing experience remains missing; the driver history is limited to the data we actually have, not automatically the entire real career.

**Driver durability** here is historic *race-completion reliability*, not biological stamina or a claim that all failures were the driver's responsibility. Team mechanical reliability, driver-caused incidents, and safety-car risk remain confounded until classified source-specific reasons are included.

The official circuit identity is essential. The branded 2026 Bahrain GP at Sepang cannot borrow Sakhir-specific track history.

## Weather is a driver interaction, not an independent outcome determinant

Race conditions affect drivers differently depending on previous wet/dry experience, developing skill and team/car reliability. The weather prototype keeps three concepts separate:

1. **Observed historical weather** labels *past* completed race conditions. It may only join earlier known results.
2. **Pre-race forecast** contains a properly sourced issue timestamp and a continuously valued chance of rain. It must have been published before the frozen prediction cutoff.
3. **Individual driver condition response** uses a historical wet-versus-dry change relative to that same driver's baseline, both for classified finishes and positions gained from qualifying. Each condition-specific deviation is shrunk by `n / (n + 4)`, so a driver with one prior wet race has much less estimated weather response than one with many. A deficit of valid wet or dry samples produces *unknown* rather than a fabricated preference.

This is a *modifier* to driver skill/form in later challenger models. Weather itself never changes a driver into a certain winner, and a single wet race cannot define a permanent driver trait. The experimental `weather_context.py` contract calculates historical wet/dry deviations and refuses forecast timestamps after inference cutoff. It does **not** yet ingest a trustworthy archived weather forecast dataset or feed weather variables to training automatically.

Rain chance, track temperature, wind, tyre performance, car setup and wet-transition timing should become separate driver × team × environment interactions when timestamped inputs are available. Historical observed race conditions must never be used as if they were a forecast made before lights out.

## Decision boundaries

The search compares models on exact Grand Prix winner hits, winner gain over pole, winner Brier, log loss, probability calibration and top-four recall. Select using the 2025 research cohort only; 2026 is a later diagnostic cohort but has already been inspected in earlier work, so it is not truly blind. A 98% exact-winner hit-rate is only a long-term aspiration. The production API and mobile app must not change until a pre-race immutable forecast record and prospective holdout evidence exist.

The original 2024 engine remains reproducible. All feature updates are tested for no-lookahead, driver/constructor temporal boundaries, weather-sample uncertainty and race-cohort parity.
