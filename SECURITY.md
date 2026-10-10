# Security policy

This is a demonstration repository built on a pinned, non-commercial-licensed
dataset snapshot. It is not approved to process real customer, regulated,
export-controlled, health, payment, or government data.

## Non-negotiable controls

- No client-side or committed secrets. `.env` files are never committed;
  `.env.example` documents safe loopback defaults only.
- The dataset snapshot is hash-verified against `provenance.json`; the engine
  fails closed on any mismatch and never serves predictions from unverified data.
- The API surface is read-only (GET); CORS is loopback-only and never allows
  credentials.
- Python dependencies install from hash-pinned lockfiles (`--require-hashes`)
  and both ecosystems are audited in CI (`pip-audit`, `npm audit`); findings on
  the production chain block merges.
- Third-party GitHub Actions are pinned to commit SHAs, and CI workflows run
  with a `contents: read` token scope.
- Test tooling (vitest, pytest) is dev-dependency only; it is not part of the
  shipped web bundle.
- The prediction ledger is append-only and chain-verified; a failed
  verification is a typed error, never a silent pass.

Report vulnerabilities privately to the repository owner. Do not open a public
issue containing exploit details or customer information.
