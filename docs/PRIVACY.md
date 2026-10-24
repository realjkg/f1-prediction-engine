# Privacy and retention

Pit Wall is anonymous. There is no registration, login, password, email,
profile or user identifier anywhere in the app or API.

## What the code guarantees

- **No browser persistence of user data.** The Rewind game's picks, scores,
  badges and preferences live in React state and reset on reload. The app sets
  no cookies and writes nothing to localStorage, sessionStorage or IndexedDB.
  Tests: `web/src/raceflow.test.tsx`, `web/src/routes/predictions.test.tsx`.
- **Scoped legacy cleanup.** Earlier builds stored the game record under
  `pitwall.record.v1`. On startup the app removes exactly that key and nothing
  else on the origin (`purgeLegacyStorage` in `web/src/lib/pitwall.ts`, tested
  in `web/src/lib/pitwall.test.ts`).
- **Service worker** caches only the app shell and content-hashed static
  assets. `/api/` responses are always fetched from the network and never
  cached (`web/public/sw.js`).
- **No access logs from our servers.** Every uvicorn launcher runs with access
  logging off, and both nginx configs set `access_log off`, so the app writes
  no per-request records with IP addresses or user agents. nginx's error log is
  limited to `crit`; a critical fault line can still include the client
  address (`engine/tests/test_privacy_logging.py`).
- **Aggregate metrics only.** `/metrics` counts requests by route and status in
  memory, with no visitor identifiers.
- **No analytics**, tracking pixels, fingerprinting or session replay.
- **Credentials stay server-side.** OpenF1 credentials are backend environment
  secrets; a failed token exchange reports a fixed message without the
  username or password.

## Retention matrix

| Data | Where | Retention | Personal? |
| --- | --- | --- | --- |
| Game picks, scores, badges, preferences | Page memory | Until reload | No identity attached |
| Legacy `pitwall.record.v1` | Browser localStorage (old builds) | Deleted on next app start | Possibly a nickname |
| F1 results, qualifying, drivers | Server dataset snapshot | Until a reviewed refresh replaces it | Public sports data |
| Predictions and evaluation evidence | Server ledger (append-only) | Kept for reproducibility | No visitor data |
| Request counts by route and status | Server memory | Until process restart | No |
| Per-request access logs (IP, user agent) | Not written by app servers | None from the app | Would be personal |
| nginx critical error lines | Container stderr | Host log retention | May include a client address |
| OpenF1 live spool and checkpoints | Private collector disk (if deployed) | Operator-defined | No visitor data |

## Outside the code's control

A hosting platform (Vercel, Render), CDN, load balancer or network in front of
the app may keep its own request logs with IP addresses. This code cannot turn
those off. Before stating that a deployment keeps no visitor data, check and
configure each of these, and record the result in the release notes.
Restarting a process clears in-memory metrics; nothing guarantees when a
browser frees page memory after a tab closes.
