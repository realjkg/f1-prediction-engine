/**
 * UI fixture data — Pit Wall game screens, pre-API-wiring.
 *
 * MOCK DATA: these files stand in for the engine's read surface until the
 * wiring task swaps `fixtures/*` imports for live fetches. Shapes are the
 * engine's wire contracts (web/src/types.ts); values are hand-authored
 * samples, including hand-authored (not computed) sha256 strings — the client
 * never verifies hashes, it displays them.
 *
 * Historic podiums below follow the real 2020–2024 results where the game
 * demo benefits from them (2020 Austrian GP, 2021 Abu Dhabi GP, 2023 Bahrain
 * GP, 2024 British GP); grids, form lines, and probabilities are illustrative.
 * A single 2024-era driver pool is reused across all seasons for simplicity.
 */

import type { DatasetIdentity, ModelId } from "../types";

export interface DriverInfo {
  driverId: string;
  /** Short display name, e.g. "Max Verstappen". */
  name: string;
  /** Three-letter timing code, e.g. "VER". */
  code: string;
  /** 2024-season team — a fixture simplification across the 2020–2024 window. */
  team: string;
}

export const DRIVERS: Record<string, DriverInfo> = {
  "1-max": { driverId: "1-max", name: "Max Verstappen", code: "VER", team: "Red Bull" },
  "44-ham": { driverId: "44-ham", name: "Lewis Hamilton", code: "HAM", team: "Mercedes" },
  "4-nor": { driverId: "4-nor", name: "Lando Norris", code: "NOR", team: "McLaren" },
  "63-rus": { driverId: "63-rus", name: "George Russell", code: "RUS", team: "Mercedes" },
  "55-sai": { driverId: "55-sai", name: "Carlos Sainz", code: "SAI", team: "Ferrari" },
  "16-lec": { driverId: "16-lec", name: "Charles Leclerc", code: "LEC", team: "Ferrari" },
  "14-alo": { driverId: "14-alo", name: "Fernando Alonso", code: "ALO", team: "Aston Martin" },
  "77-bot": { driverId: "77-bot", name: "Valtteri Bottas", code: "BOT", team: "Sauber" },
  "81-pia": { driverId: "81-pia", name: "Oscar Piastri", code: "PIA", team: "McLaren" },
  "11-per": { driverId: "11-per", name: "Sergio Pérez", code: "PER", team: "Red Bull" },
  "10-gas": { driverId: "10-gas", name: "Pierre Gasly", code: "GAS", team: "Alpine" },
  "27-hul": { driverId: "27-hul", name: "Nico Hülkenberg", code: "HUL", team: "Haas" },
};

export function driverName(driverId: string): string {
  return DRIVERS[driverId]?.name ?? driverId;
}

/** The pinned dataset every fixture record claims — mirrors data/snapshot provenance. */
export const MOCK_DATASET: DatasetIdentity = {
  id: "2026.10.0",
  // Fixture digest — a display sample, not a real snapshot hash.
  sha256:
    "9f2c7a41e5b8d03f6c2a94e17d5b8f0a3c6e9d2b5f8a1c4e7d0f3a6b9c2e5d8f",
};

/**
 * Snapshot provenance time — records carry it verbatim (the engine derives
 * generatedAt from the dataset, never the wall clock).
 */
export const MOCK_GENERATED_AT = "2026-10-09T00:00:00Z";

/** dataLimitations carried by every record — the pinned dataset's own declarations. */
export const MOCK_DATA_LIMITATIONS = [
  "no in-race telemetry in the pinned window",
  "no weather features before the 2023 rounds in the snapshot",
];

/** Spec's evidence-basis banner — what a REAL_MODELS ledger record carries. */
export const REAL_MODELS_EVIDENCE_BASIS =
  "REAL MODELS — PINNED DATASET 2020–2024 — NO LIVE INFERENCE";

/**
 * engine/f1engine/models.py FEATURE_COLUMNS — m1/m2 diagnostics.
 * Order must match the engine's tuple; the UI only displays it.
 */
export const FULL_FEATURE_SET = [
  "starts",
  "form_finish_mean",
  "form_finish_mean_all",
  "q_best_ms",
  "q_delta_teammate_ms",
  "q_delta_pole_ms",
  "team_points_mean",
  "track_finish_mean",
];

/** The heuristic's honest subset — engine models.py _FORM_FEATURES. */
export const FORM_FEATURE_SET = [
  "form_finish_mean",
  "form_finish_mean_all",
  "q_delta_pole_ms",
];

/** Fixture model seeds (engine MODEL_SEED); null = no stochastic component. */
export const FIXTURE_SEEDS: Record<ModelId, number | null> = {
  "m1-gbm": 2026,
  "m2-logit": null,
  "m3-form": null,
};
