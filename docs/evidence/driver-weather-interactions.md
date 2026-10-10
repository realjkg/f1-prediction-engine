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

Rain chance, track temperature, wind, tire performance, car setup and wet-transition timing should become separate driver × team × environment interactions when timestamped inputs are available. Historical observed race conditions must never be used as if they were a forecast made before lights out.

## Decision boundaries

The search compares models on exact Grand Prix winner hits, winner gain over pole, winner Brier, log loss, probability calibration and top-four recall. Select using the 2025 research cohort only; 2026 is a later diagnostic cohort but has already been inspected in earlier work, so it is not truly blind. A 98% exact-winner hit-rate is only a long-term aspiration. The production API and mobile app must not change until a pre-race immutable forecast record and prospective holdout evidence exist.

The original 2024 engine remains reproducible. All feature updates are tested for no-lookahead, driver/constructor temporal boundaries, weather-sample uncertainty and race-cohort parity.


## Singapore qualifying, October 10, 2026: why session adaptation matters

The official Formula 1 qualifying report recorded:

- **Verstappen P1**, 1:31.373.
- **Leclerc P2**, 1:31.427, only 0.054 seconds behind Verstappen.
- **Hamilton P3**, 1:31.496, 0.123 seconds behind Verstappen.

Hamilton led both Q1 and Q2; Leclerc improved late in Q3 to finish
ahead of his teammate. The rain-affected Sprint preceded a later drier
qualifying session, underscoring the risk of comparing raw times between
different sessions and conditions.

Source: [Formula 1 Singapore qualifying report, published October 10,
2026](https://www.formula1.com/en/latest/article/verstappen-beats-leclerc-to-pole-position-for-the-singapore-gp.7yum1V3S9aSTyj3Zzzs0Y9).

The `session_progression.py` challenger normalizes each Q1, Q2 and Q3
time **against the fastest valid time within that same session**, then
records the driver's relative-gap improvement into Q3. Thus Leclerc's
late improvement is not mistakenly labeled declining ability because
Hamilton was initially quicker. Comparisons with the teammate help
partially control for car performance; tire choice, team strategy, traffic,
setup, track evolution and gaps between clean laps are *not* yet isolated.

This qualifies as *post-qualifying* known evidence for the October 11 race,
**not** a model forecast of the winner. The Singapore Grand Prix outcome is
not present in the October 10 training snapshot. Stage 2 needs session
availability timestamps and a pre-race freeze before the current event's
data can feed real production predictions.
