import type { ConfigView } from "../types";

/** Fixture view of GET /api/config — the Settings screen's operating contract. */
export const CONFIG: ConfigView = {
  engineVersion: "0.7.0",
  datasetVersion: "2026.10.0",
  advisoryOnly: true,
  advisoryNotice:
    "Every prediction on every screen is advisory-only, computed from the pinned 2020–2024 dataset. Nothing here predicts live races, and nothing here is betting advice.",
  consensusThreshold: 0.15,
  briefMode: "fixture",
};

/** TODO(api-wiring): GET /api/config replaces this constant (todo_gFifvtGU). */
export function configView(): ConfigView {
  return CONFIG;
}
