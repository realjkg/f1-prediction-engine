# Weather as an interaction, not a race-result determinant

**Design correction:** weather changes the physical conditions and how a
driver/team/tire package can perform. It is not an independent reason to pick
a race winner. The forecast's effect belongs in learned conditional performance
interactions, behind a time-stamped source-evidence gate.

## Conditional feature design

Capture forecast probabilities before the race for **dry**, **mixed/drying**
and **wet** regimes. Treat race-start and source-publication times as first-
class values. For each driver, estimate historically observed skill residuals
in those regimes, **after controlling for constructor, qualifying position,
circuit, race era and sample composition**. The same driver can have different
advantages in mixed and persistently wet conditions.

`condition_interaction.py` includes an isolated inference adapter:

```
score(driver) =
  P(mixed) * shrink(mixed_starts) * skill_residual(mixed)
  + P(wet) * shrink(wet_starts) * skill_residual(wet)

P(win | forecast, driver-experience) =
  normalize(P(win | existing model) * exp(strength * score(driver)))
```

Here `shrink(n)=n/(n+8)` is the initial **experimental** sample-count
regularizer. `strength` defaults to **0**, causing precisely zero behavioral
change to the deployed predictor. Its upper bound is 1 for the initial
candidate; **both the shrinkage and strength must be selected through
chronological validation**, not chosen to match a known outcome.

The applicant model may boost, reduce or leave a driver's probability
unchanged depending on *independently sourced past performance*. No named
driver gets a built-in boost or penalty. When the forecast is fully dry,
wet-skill residuals have zero effect. The baseline model always contributes.

## Source and as-of controls

- Forecast: regime probabilities, source SHA-256 digest, publication time,
  cutoff time and GP start time. Reject a forecast issued after cutoff or a
  prediction issued after race start.
- Driver profiles: immutable, source-verified estimates fitted on **past**
  races only, with profile-source digest and latest effective historical date.
  Reject profile evidence dated after prediction cutoff.
- No source: no weather adjustment. No individual history: neutral effect.
  Few prior condition-matched races: strong shrinkage toward neutral.
- A retrospective race's *actual* weather is **not** an acceptable
  substitute for the historical forecast unless verified to have been known
  at the prediction cutoff.
- Current upstream race snapshots store results, qualifying and sprints but
  **do not carry historical forecast issue times**. Do not fabricate them or
  bootstrap driver wet-skill features from classified outcomes without
  condition-specific prior source data.
- Optional inference applies to race-win distributions as a challenger; it
  does **not** autonomously rewrite the published ensemble or model registry,
  and does not override podium or top-four distributions.

## Empirical qualification still required

Gather licensed pre-race weather and circuit/track condition telemetry with
timestamps. Link it to historical entrants and results; train shrinkage and
weather interactions while controlling for constructor strength, era and track
effects. Score on chronological unseen races with pole-position, current
qualifying, Brier/log loss, exact winner hits, calibration and top-four
recall. Publish subgroup comparisons for dry, mixed, heavy rain and uncertain
forecasts, including confidence intervals.

A narrative observation that Verstappen excels in the rain or another driver
struggles is a **hypothesis to test**, not a hard-coded weather rule.
Race-specific examples are too few to classify ability on their own.
Weather may materially change a probability in a well-evidenced case, but
neither weather nor the driver name determines the outcome.

**Status:** Gate-complete offline interface with invariant/refusal tests.
**Not** a trained wet-weather model, live weather connector, validated
probability improvement or deployed inference feature. Issue #25 tracks those
release requirements. Production promotion remains blocked.
