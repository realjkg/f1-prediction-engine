# F1 Prediction Engine

Adapt Cloud's standalone F1 race-prediction demonstrator — the customer-facing
counterpart to the [Landing Zone accelerator](https://github.com/realjkg/agent-private-landing-zone).
Where the accelerator shows sovereign governance in minutes, this shows what
the AI actually does: it predicts, it shows its work, and it proves how often
it was right. All predictions are advisory-only evidence records.

**Status: Milestone 1 scaffold.** Both runtimes stand up and CI is green; the
engine seams are typed stubs (`NotImplementedError`) pending their owning
tasks. Nothing predicts yet — and every future screen will carry its
evidence-basis label rather than pretend otherwise.

## The five capabilities

| Capability | What the demo shows |
| --- | --- |
| Pinned dataset | 2020–2024 Jolpica-derived snapshot, hash-verified against `provenance.json` before every run |
| Three models + ensemble | `m1-gbm`, `m2-logit`, `m3-form` predict independently; a weighted ensemble blends them and flags cross-model disagreement numerically |
| Evidence ledger | Every prediction is a sha256-chained, advisory-only record with declared limitations |
| Backtest accuracy | Expanding-window backtest vs actual results — winner hit rate, podium@3, Brier — per model and ensemble |
| One-command demo | `make demo` — verify → predict → prove → narrate → serve, repeatable to the byte |

## Quickstart

Prerequisites: Python 3.12+, Node 20+.

```bash
make engine-install
make web-install
make demo      # Milestone 1: prints the implemented-later sequence
make test      # pytest (engine) + vitest (web)
make lint      # ruff (engine) + tsc --noEmit (web)
```

PWA development server: `npm --prefix web run dev`, then open the printed URL.
The app is installable (manifest + service worker; registration is
production-only). Mobile-first: single column, bottom tab navigation, five
routes — Race (default), Models, Evidence, Observability, Settings.

## Repo layout

| Path | Contents |
| --- | --- |
| `engine/f1engine/` | FastAPI app factory + typed seams: ingestion, features, models, ensemble, evidence, brief, observability |
| `engine/tests/` | pytest — one flat file per domain |
| `web/` | Vite + React + TS PWA (Race, Models, Evidence, Observability, Settings) |
| `data/snapshot/` | Pinned dataset version, provenance template, data licenses |
| `.github/workflows/` | `pr-validation`: pytest + ruff (engine), vitest + tsc (web); SHA-pinned actions, `contents: read` |

## Data & licensing

Historical data derives from [jolpica-f1](https://github.com/jolpica/jolpica-f1)
(CC BY-NC-SA 4.0) and [OpenF1](https://openf1.org) (free-tier, non-commercial).
See [data/snapshot/DATA_LICENSE.md](data/snapshot/DATA_LICENSE.md) for full
attribution, rate limits, and the commercialization caveat. Neutral branding;
no Formula 1 marks.

## License

MIT — see [LICENSE](LICENSE).
