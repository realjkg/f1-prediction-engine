# F1 Prediction Engine — Pit Wall

Adapt Cloud's standalone F1 race-prediction demonstrator — the customer-facing
counterpart to the [Landing Zone accelerator](https://github.com/realjkg/agent-private-landing-zone).
Where the accelerator shows sovereign governance in minutes, this shows what
the AI actually does: it predicts, it shows its work, and it proves how often
it was right.

> **Advisory-only.** Every prediction this app produces is an advisory-only
> evidence record with declared limitations. Nothing here is betting advice,
> and nothing implies otherwise.

**Status: Milestone 1 complete.** Real models train on the pinned dataset,
predict every 2024 round through the ensemble, score against actual results,
and ship that proof in a hash-chained ledger — reproducible to the byte
([two-run determinism evidence](docs/evidence/determinism-run.md)).

## One-command quickstart

Prerequisites: Python 3.12+, Node 20+. No API keys, no network after install
(the pinned dataset ships in the repo).

```bash
make demo          # verify → predict → prove → narrate → serve
```

`make demo` verifies the snapshot hash, trains the three models with fixed
seeds, predicts all 24 scoreable 2024 rounds, backtests against actual
results, writes the evidence ledger, prints the fixture race briefs, then
serves the engine API. Expect:

- **Banner:** `F1 Prediction Engine v0.1.0 — REAL MODELS — PINNED DATASET 2020–2024 — NO LIVE INFERENCE`
- **API:** `http://127.0.0.1:8000` (docs at `/docs`, Prometheus at `/metrics`)
- **The proof, in the log:** `backtest: 24 rounds scored — winner hit rate ensemble=0.25, m1-gbm=0.29, m2-logit=0.29, m3-form=0.21`

Then serve the PWA and open it (same machine):

```bash
npm --prefix web run dev    # → http://localhost:5173 (proxies /api to :8000)
```

Other entry points: `make test` (pytest + vitest), `make lint`
(ruff + tsc --noEmit), `make refresh-data` (offline tool to regenerate the
pinned snapshot from Jolpica — rate-aware, resumable, never a runtime step).

## What the app demonstrates

| Capability | What the demo shows |
| --- | --- |
| Pinned dataset | 2020–2024 Jolpica-derived snapshot, hash-verified against `provenance.json` before every run |
| Three models + ensemble | `m1-gbm` (gradient-boosted trees), `m2-logit` (logistic regression), `m3-form` (rolling-form baseline) predict independently; a weighted ensemble blends them and flags cross-model disagreement numerically (`LOW_CONSENSUS`) |
| Evidence ledger | Every prediction is a sha256-chained, advisory-only record with declared limitations |
| Backtest accuracy | Expanding-window backtest vs actual results — winner hit rate, podium@3, Brier — per model and ensemble |
| One-command demo | `make demo` — repeatable to the byte |

## Pit Wall — the game on top

**Race Rewind** is the core loop: pick any completed 2020–2024 round, read the
call sheet (qualifying grid + form — *this is all the machine knows*), lock
P1/P2/P3 inside a 30-second timer, and get the reveal: your podium vs the
actual result vs every model's card, with engine-computed scoring (the client
never invents scores — they come from `GET /api/races/{raceId}/score`).
Scoring: +5 per position-exact podium hit, +3 for calling the winner, +1 for a
near miss (your pick finished P4) — 0–18 a round, **doubled on Coin Flip
Rounds** where the ensemble flags `LOW_CONSENSUS`, because a split machine
means your gut is the only edge. Exact hits extend a streak (flame at 3); six
badges ship, from *First Exact Podium* to *Data Nerd*. Your pit-wall record
lives in `localStorage` — no accounts in Milestone 1. Hindsight is
acknowledged on every reveal card: you may remember these results; the models
do not get that memory.

## The evidence contract

Everything the UI shows derives from one schema-valid JSON record, and every
claim ships with its receipts:

- **Hash-chained ledger** — every prediction and backtest record carries the
  sha256 of the previous record; the chain is re-verified on every demo run,
  and tampering is detectable.
- **Backtest metrics, not vibes** — expanding-window over 2024: winner hit
  rate, podium@3, Brier score, per model and ensemble. The predictions in the
  ledger are exactly the ones the backtest scored.
- **Deterministic runs** — two `make demo` runs produce byte-identical
  ledgers (fixed seeds, pinned dataset, fixture briefs; no wall-clock time in
  evidence). Proof: [docs/evidence/determinism-run.md](docs/evidence/determinism-run.md).
- **Advisory labels everywhere** — `advisoryOnly: true` and declared
  `dataLimitations` on every record; the `LOW_CONSENSUS` flag is advisory
  (flagged, never suppressed).

## PWA install

The web app is an installable, mobile-first PWA (manifest + service worker;
single column, bottom tabs; routes: Race, Models, Evidence, Brief,
Observability, Settings).

- **Android/Chrome (desktop):** open the served app → install prompt, or
  menu → *Install app* / *Add to Home screen*.
- **iOS/Safari:** Share → *Add to Home Screen*.

Service-worker registration is production-only (`npm run build` + preview or
a served `dist/`); the dev server behaves like a plain web app.

## Native shells (iOS + Android)

The same PWA ships as a native app via
[Capacitor](https://capacitorjs.com) — there is no second app codebase.
`capacitor.config.ts` sits next to the web app; `web/android/` is a Gradle
project and `web/ios/` an Xcode project, each wrapping the built web bundle.
The copied web assets (`android/app/src/main/assets/public`,
`ios/App/App/public`) are gitignored: every `cap sync` regenerates them from
`dist/`.

Prerequisites: [Android Studio](https://developer.android.com/studio) for
Android; [Xcode](https://developer.apple.com/xcode/) on macOS for iOS.

```bash
cd web
npm run build         # tsc --noEmit + vite build → dist/
npx cap sync          # copies dist/ + plugin config into both native projects
npx cap run android   # device/emulator via Android Studio
npx cap run ios       # macOS + Xcode only
```

**macOS caveat:** iOS builds (and `cap run ios`) require Xcode, which exists
only on macOS — iOS verification needs macOS/Xcode and is not covered by this
repo's Linux CI. The `ios/` project files are committed as generated; `npx cap
sync` covers both platforms on Linux. Native store builds and store deployment
are explicitly out of scope for Milestone 1.

## Repo layout

| Path | Contents |
| --- | --- |
| `engine/f1engine/` | FastAPI app + implemented engine: ingestion, features, models, ensemble, scoring, evidence ledger, brief, observability |
| `engine/tests/` | pytest — one flat file per domain |
| `web/` | Vite + React + TS PWA (Race Rewind, Model Gauntlet, Evidence Room, Brief, Observability, Settings) + Capacitor shells |
| `data/snapshot/` | Pinned dataset (`DATASET_VERSION`, `provenance.json`, parquet) + `DATA_LICENSE.md` |
| `docs/evidence/` | Recorded integration evidence (determinism runs) |
| `scripts/` | `demo.py` (one-command demo), `refresh-data.py` (offline snapshot regen), `generate-driver-directory.py` |
| `.github/workflows/` | `pr-validation`: pytest + ruff (engine), vitest + tsc + Capacitor sync smoke (web); SHA-pinned actions, `contents: read` |

## Data & licensing

Historical data derives from [jolpica-f1](https://github.com/jolpica/jolpica-f1)
(CC BY-NC-SA 4.0) and [OpenF1](https://openf1.org) (free-tier, non-commercial).
The pinned 2020–2024 snapshot ships in the repo and is the runtime source of
truth; Jolpica/OpenF1 refresh is an explicit offline step (`make refresh-data`)
with provenance capture — never a runtime dependency. See
[data/snapshot/DATA_LICENSE.md](data/snapshot/DATA_LICENSE.md) for full
attribution, rate limits, and the commercialization caveat. Neutral branding;
no Formula 1 marks.

## License

MIT — see [LICENSE](LICENSE).
