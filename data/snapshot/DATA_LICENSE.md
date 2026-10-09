# Data License & Attribution

The pinned dataset (`data/snapshot/`, 2020–2024 seasons) is community-provided
and only usable under the terms below. Milestone 1 runs entirely from the
committed snapshot; upstream refresh is an explicit offline step (rate-limit
aware), never a runtime dependency.

## Jolpica (primary historical source)

- Project: [jolpica-f1](https://github.com/jolpica/jolpica-f1) — the Ergast successor.
- License: [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
- Obligations honored here: attribution (this file + `provenance.json`), no
  commercial redistribution of the snapshot, share-alike for adaptations.
- Rate limits for the offline refresh: 4 requests/second, 500 requests/hour
  (unauthenticated).

## OpenF1 (2023+ detail source)

- Project: [openf1.org](https://openf1.org) — lap/timing/weather detail.
- Terms: free-tier, non-commercial use. Confirm current terms before any
  commercialization.
- Rate limits for the offline refresh: 3 requests/second, 30 requests/minute.

## Demonstrator posture

- Neutral branding: no Formula 1 marks, logos, or official imagery.
- The snapshot is generated only by the explicit refresh script, which records
  provider, endpoint, retrieval date, and content hash in `provenance.json`;
  the demo refuses to run on hash mismatch (`DATA_SNAPSHOT_MISMATCH`).
- Open question (non-blocking): commercial redistribution of the snapshot
  requires counsel review of both licenses before it happens.
