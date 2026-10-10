#!/bin/sh
set -eu

# A standalone server cannot synthesize model predictions; generate the
# canonical signed-chain evidence inside the API container, before serving.
# Deterministic replay is intentional for the demonstrator. For a future
# promoted 2026 inference service, replace this preflight with an explicit
# verified model registry loader.
python scripts/demo.py \
  --data-dir "${F1E_DATA_DIR:-data/snapshot}" \
  --ledger "${F1E_LEDGER_PATH:-data/evidence/ledger.jsonl}" \
  --season "${F1E_DEMO_SEASON:-2024}" \
  --no-serve --no-brief

exec python -m uvicorn f1engine.app:create_app \
  --factory --host 0.0.0.0 --port 8000 --workers 1
