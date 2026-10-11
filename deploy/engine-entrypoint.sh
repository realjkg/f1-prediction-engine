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

# Secure production transport: TLS 1.3-only OpenSSL context + mutual
# certificate validation for the Nginx-to-engine channel. No fallback.
if [ "${F1E_REQUIRE_TLS:-0}" = "1" ]; then
  for file in /run/tls/engine.crt /run/tls/engine.key /run/tls/ca.crt; do
    if [ ! -r "$file" ]; then
      echo "TLS 1.3 production startup refused: required certificate unavailable" >&2
      exit 1
    fi
  done
  exec python -m uvicorn f1engine.app:create_app \
    --factory --host 0.0.0.0 --port 8000 --workers 1 \
    --ssl-certfile /run/tls/engine.crt \
    --ssl-keyfile /run/tls/engine.key \
    --ssl-ca-certs /run/tls/ca.crt \
    --ssl-cert-reqs 2
fi

# Explicitly local/demo-only plaintext mode: secure Compose always sets
# F1E_REQUIRE_TLS=1 and is the only permitted production deployment.
exec python -m uvicorn f1engine.app:create_app \
  --factory --host 0.0.0.0 --port 8000 --workers 1
