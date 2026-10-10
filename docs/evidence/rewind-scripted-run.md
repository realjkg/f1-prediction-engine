# Scripted Race Rewind — integration evidence

One full Pit Wall game loop, driven against the **live** `make demo` stack
(engine API on `:8000`, PWA dev server on `:5173`) in a headless browser
(agent-browser, Chrome 155) at **375 CSS px / DPR 2** — the mobile-first
contract viewport.

- Date: 2026-10-10
- Tested head SHA: `54ba5da3c49cfc4899e6785c3f7f86f56c449234` (the only commit
  after this capture is this evidence document itself — no code delta)
- QA uploads: `obvious autobuild upload`, `tc-1`…`tc-5`, verdicts `pass`,
  recorded against the SHA above
- Round played: 2024 R1 — Bahrain Grand Prix

## The loop, as captured

1. **Catalog** (`tc-1`) — the round picker renders 107 completed 2020–2024
   rounds served live by `GET /api/races`; 2024 R1–R24 first.
2. **Call sheet** (`tc-2`) — picked R1 Bahrain; the sheet loads the engine's
   prediction record for the round (20-driver field) — *this is all the
   machine knows*: entrants only, no result hints, dataset digest attached.
3. **Lock** — picked VER / PER / SAI and locked; the lock is scored by the
   engine (`GET /api/races/bahrain-grand-prix/score` path), not the client.
4. **Reveal** (`tc-3`, recording `tc-3-flow.webm`, score card `tc-6` within
   `tc-3`'s upload) — **EXACT PODIUM** on a **LOW_CONSENSUS · COIN FLIP**
   round: engine-computed **+36 pts** (base 18 = 3 × exact +5 + winner bonus
   +3, doubled ×2), streak, and three badges earned (First Exact Podium ·
   Beat The Ensemble · Perfect Round). The reveal shows the actual podium
   beside your call and every model's card — ensemble (weighted blend, VER
   83% win call), `m1-gbm`, `m2-logit`, `m3-form` — each with per-position
   ✓/→ classifications. Hindsight note visible: *"Open replay — the models
   never saw this result; you may remember it."* **Next round →** and
   **Open the evidence** affordances present.
5. **Model Gauntlet** (`tc-4`) — standings across played rounds: You 36,
   `m3-form` 36, `m2-logit` 28, `m1-gbm` 18, Ensemble 18 — plus the
   24-round 2024 backtest table (winner hit: m1 29%, m2 29%, m3 21%,
   Ensemble 25%; podium@3 and mean Brier per model). The backtest numbers
   match the determinism run's recorded metrics exactly.
6. **Evidence Room** (`tc-5`) — the hash-chained ledger as served:
   25 of 25 records, **chain valid: yes**, dataset `2026.10.0 · 94762d23…`,
   per-record digests, genesis chain-from, consensus flag, declared
   limitations.

## Found during this run (fixed on this branch)

The scripted loop initially could not load any prediction: `make demo` wrote
its ledger to `data/ledger.jsonl` while the served API read
`data/evidence/ledger.jsonl` (`DEFAULT_LEDGER_PATH`, `.env.example`) — the
served demo showed an empty evidence store. Fixed in
`fix(demo): serve the ledger the demo writes` (demo default aligned + parent
dir created + gitignore path); the API then served 25/25 records with a valid
chain before the captures above were taken.

## Reproduce

```bash
make demo                      # terminal 1 — engine API on :8000
npm --prefix web run dev       # terminal 2 — PWA on :5173
# open http://localhost:5173 at 375×812 (DPR 2) → pick 2024 R1 →
# call VER/PER/SAI → Lock → reveal → Models → Evidence
```
