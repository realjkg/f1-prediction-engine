#!/bin/sh
set -eu
: "${F1E_LIVE_SESSION_KEY:?Verified OpenF1 session key required}"
: "${F1E_LIVE_SEASON:?Race season required}"
: "${F1E_LIVE_RACE_ID:?Race slug required}"
: "${F1E_LIVE_TOTAL_LAPS:?Verified race distance required}"
: "${F1E_LIVE_ENTRANTS:?Verified driver numbers required}"
: "${F1E_OPENF1_RIGHTS_REF:?Source publication rights reference required}"

set -- python /app/scripts/run-live-ingest.py \
  --session-key "$F1E_LIVE_SESSION_KEY" \
  --season "$F1E_LIVE_SEASON" \
  --race-id "$F1E_LIVE_RACE_ID" \
  --total-laps "$F1E_LIVE_TOTAL_LAPS" \
  --entrants "$F1E_LIVE_ENTRANTS" \
  --trace "/app/data/live/trace.jsonl" \
  --artifacts "/app/data/live/artifacts" \
  --spool "/app/data/live/spool.jsonl" \
  --heartbeat "/app/data/live/heartbeat.json" \
  --rights-reference "$F1E_OPENF1_RIGHTS_REF"
if [ -n "${F1E_LIVE_PRIOR_FILE:-}" ]; then
  set -- "$@" --prior "$F1E_LIVE_PRIOR_FILE"
fi
exec "$@"
