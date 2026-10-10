/**
 * Prediction-record fixtures — mirror GET /api/predictions/{raceId} and the
 * ledger records behind GET /api/evidence (engine PredictionRecord wire shape).
 *
 * Per-race model voices (hand-authored, contract-shaped):
 * - m1-gbm is sharp and feature-driven; m2-logit spreads mass; m3-form rides
 *   recent finishes. The 2021 Abu Dhabi round splits the models (m2 backs
 *   Hamilton) — the coin-flip round. The 2024 British GP is the spec's own
 *   example record: every model backs Verstappen; Hamilton won.
 *
 * recordSha256 / prevRecordSha256 strings are fixture samples (the client
 * never verifies hashes) — but the chain is coherent: record N+1 names
 * record N's digest, like the engine's ledger does.
 */

import type {
  Consensus,
  EnsembleVerdict,
  ModelId,
  ModelPrediction,
  PredictionRecord,
  ProbabilityMap,
  RaceSummary,
} from "../types";
import {
  FIXTURE_SEEDS,
  FORM_FEATURE_SET,
  FULL_FEATURE_SET,
  MOCK_DATA_LIMITATIONS,
  MOCK_DATASET,
  MOCK_GENERATED_AT,
  REAL_MODELS_EVIDENCE_BASIS,
} from "./drivers";
import { RACES } from "./races";

const WEIGHTS: Record<ModelId, number> = {
  "m1-gbm": 0.5,
  "m2-logit": 0.3,
  "m3-form": 0.2,
};

interface ModelSpec {
  modelId: ModelId;
  winner: ProbabilityMap;
  podium: ProbabilityMap;
}

interface RaceSpec {
  race: RaceSummary;
  models: [ModelSpec, ModelSpec, ModelSpec];
  ensemble: { winner: ProbabilityMap; podium: ProbabilityMap; consensus: Consensus };
}

/** Hand-authored record digests — fixture samples, chained in list order. */
const FIXTURE_RECORD_HASHES = [
  "3f2a8c4e61b0d5f907a2c8e419b35d7fa06be2c483d56f18b4a02c9ef571d3a8",
  "7b09e1d5a3c684f02d5b7e9c1a4f6d8b03c5e7a19d2f4b6c8e0a3d5f7b1c4e6a",
  "c14f8a2e6b3d7059f1a4c8e2b6d09f3a5c7e1b4d8f2a6c0e3b7d5f9a1c4e8b2d",
  "e8b2d6f0a4c3875e91d6f2a8b4c0e3d7f5a19c6e2b8d4f0a6c3e7b1d5f9a3c08",
  "5d9f1a3c7e2b6840a8e4d2c6f0b8a3e5c7d19f6a2e4c8b0d3f5a7c1e9b4d6f28",
  "a63e0b8d4f2a5719c6e8d3a5b7f0c2e4a8d6f1b3c5e7a9d0f2b4c6e8a1d3f5b7",
];

function trainedThrough(
  modelId: ModelId,
  season: number,
  round: number,
): ModelPrediction["diagnostics"] {
  return {
    // Labels are strictly before (season, round) — mirrors the engine's as-of rule.
    trainedThroughSeason: season,
    trainedThroughRound: round - 1,
    featuresUsed: modelId === "m3-form" ? [...FORM_FEATURE_SET] : [...FULL_FEATURE_SET],
    seed: FIXTURE_SEEDS[modelId],
  };
}

function buildModels(
  race: RaceSummary,
  spec: RaceSpec,
): Record<ModelId, ModelPrediction> {
  const built = {} as Record<ModelId, ModelPrediction>;
  for (const model of spec.models) {
    built[model.modelId] = {
      raceId: race.raceId,
      modelId: model.modelId,
      winner: model.winner,
      podium: model.podium,
      generatedAt: MOCK_GENERATED_AT,
      datasetDigest: MOCK_DATASET.sha256,
      diagnostics: trainedThrough(model.modelId, race.season, race.round),
    };
  }
  return built;
}

function buildVerdict(race: RaceSummary, spec: RaceSpec): EnsembleVerdict {
  return {
    raceId: race.raceId,
    winner: spec.ensemble.winner,
    podium: spec.ensemble.podium,
    consensus: spec.ensemble.consensus,
    weightsUsed: { ...WEIGHTS },
  };
}

function buildRecord(spec: RaceSpec, index: number): PredictionRecord {
  const chained = index > 0 ? FIXTURE_RECORD_HASHES[index - 1] : null;
  return {
    schemaVersion: 1,
    recordType: "prediction",
    predictionId: `${spec.race.season}-r${spec.race.round}-${spec.race.raceId}`,
    race: {
      season: spec.race.season,
      round: spec.race.round,
      raceId: spec.race.raceId,
      name: spec.race.name,
    },
    generatedAt: MOCK_GENERATED_AT,
    dataset: { ...MOCK_DATASET },
    evidenceBasis: REAL_MODELS_EVIDENCE_BASIS,
    models: buildModels(spec.race, spec),
    ensemble: buildVerdict(spec.race, spec),
    advisoryOnly: true,
    dataLimitations: [...MOCK_DATA_LIMITATIONS],
    prevRecordSha256: chained,
    recordSha256: FIXTURE_RECORD_HASHES[index],
  };
}

const SPECS: RaceSpec[] = [
  {
    // 2020 Austrian GP — Bottas won from Leclerc and Norris; Hamilton P4.
    race: RACES[0],
    models: [
      {
        modelId: "m1-gbm",
        winner: { "77-bot": 0.36, "44-ham": 0.24, "1-max": 0.16, "16-lec": 0.12, "4-nor": 0.08, "55-sai": 0.04 },
        podium: { "77-bot": 0.82, "16-lec": 0.66, "4-nor": 0.61, "44-ham": 0.55, "1-max": 0.54, "55-sai": 0.32 },
      },
      {
        modelId: "m2-logit",
        winner: { "77-bot": 0.3, "44-ham": 0.26, "1-max": 0.18, "16-lec": 0.14, "4-nor": 0.08, "55-sai": 0.04 },
        podium: { "77-bot": 0.78, "44-ham": 0.68, "16-lec": 0.62, "4-nor": 0.58, "1-max": 0.5, "55-sai": 0.3 },
      },
      {
        modelId: "m3-form",
        winner: { "77-bot": 0.28, "44-ham": 0.25, "16-lec": 0.17, "1-max": 0.16, "4-nor": 0.09, "55-sai": 0.05 },
        podium: { "77-bot": 0.74, "16-lec": 0.64, "4-nor": 0.6, "44-ham": 0.58, "1-max": 0.52, "55-sai": 0.33 },
      },
    ],
    ensemble: {
      winner: { "77-bot": 0.32, "44-ham": 0.25, "1-max": 0.17, "16-lec": 0.14, "4-nor": 0.08, "55-sai": 0.04 },
      podium: { "77-bot": 0.8, "16-lec": 0.65, "44-ham": 0.59, "4-nor": 0.58, "1-max": 0.53, "55-sai": 0.31 },
      consensus: { podiumSpread: 0.06, flag: "OK" },
    },
  },
  {
    // 2021 Abu Dhabi GP — the coin-flip round: m2 backs Hamilton; Verstappen won.
    race: RACES[1],
    models: [
      {
        modelId: "m1-gbm",
        winner: { "1-max": 0.44, "44-ham": 0.36, "55-sai": 0.1, "77-bot": 0.06, "16-lec": 0.04 },
        podium: { "1-max": 0.86, "44-ham": 0.8, "55-sai": 0.58, "16-lec": 0.42, "77-bot": 0.36 },
      },
      {
        modelId: "m2-logit",
        winner: { "44-ham": 0.42, "1-max": 0.38, "55-sai": 0.11, "77-bot": 0.05, "16-lec": 0.04 },
        podium: { "44-ham": 0.84, "1-max": 0.82, "55-sai": 0.6, "16-lec": 0.4, "77-bot": 0.38 },
      },
      {
        modelId: "m3-form",
        winner: { "1-max": 0.4, "44-ham": 0.38, "55-sai": 0.12, "16-lec": 0.06, "77-bot": 0.04 },
        podium: { "1-max": 0.83, "44-ham": 0.81, "55-sai": 0.57, "16-lec": 0.44, "77-bot": 0.35 },
      },
    ],
    ensemble: {
      winner: { "1-max": 0.42, "44-ham": 0.38, "55-sai": 0.11, "77-bot": 0.05, "16-lec": 0.04 },
      podium: { "1-max": 0.85, "44-ham": 0.81, "55-sai": 0.58, "16-lec": 0.42, "77-bot": 0.37 },
      consensus: { podiumSpread: 0.19, flag: "LOW_CONSENSUS" },
    },
  },
  {
    // 2022 Saudi Arabian GP — Verstappen from Sainz and Leclerc.
    race: RACES[2],
    models: [
      {
        modelId: "m1-gbm",
        winner: { "1-max": 0.42, "16-lec": 0.26, "55-sai": 0.14, "44-ham": 0.08, "63-rus": 0.06, "4-nor": 0.04 },
        podium: { "1-max": 0.84, "16-lec": 0.68, "55-sai": 0.6, "44-ham": 0.48, "63-rus": 0.4 },
      },
      {
        modelId: "m2-logit",
        winner: { "1-max": 0.38, "16-lec": 0.28, "55-sai": 0.16, "44-ham": 0.09, "63-rus": 0.05, "4-nor": 0.04 },
        podium: { "1-max": 0.82, "16-lec": 0.7, "55-sai": 0.62, "44-ham": 0.5, "63-rus": 0.38 },
      },
      {
        modelId: "m3-form",
        winner: { "1-max": 0.4, "16-lec": 0.27, "55-sai": 0.15, "44-ham": 0.08, "63-rus": 0.06, "4-nor": 0.04 },
        podium: { "1-max": 0.83, "16-lec": 0.69, "55-sai": 0.61, "44-ham": 0.49, "63-rus": 0.39 },
      },
    ],
    ensemble: {
      winner: { "1-max": 0.4, "16-lec": 0.27, "55-sai": 0.15, "44-ham": 0.08, "63-rus": 0.06, "4-nor": 0.04 },
      podium: { "1-max": 0.83, "16-lec": 0.69, "55-sai": 0.61, "44-ham": 0.49, "63-rus": 0.39 },
      consensus: { podiumSpread: 0.05, flag: "OK" },
    },
  },
  {
    // 2023 Bahrain GP — Verstappen, Pérez, Alonso; Hamilton P4.
    race: RACES[3],
    models: [
      {
        modelId: "m1-gbm",
        winner: { "1-max": 0.52, "11-per": 0.2, "16-lec": 0.1, "44-ham": 0.08, "14-alo": 0.06, "55-sai": 0.04 },
        podium: { "1-max": 0.88, "11-per": 0.7, "14-alo": 0.62, "16-lec": 0.48, "44-ham": 0.44 },
      },
      {
        modelId: "m2-logit",
        winner: { "1-max": 0.46, "11-per": 0.24, "44-ham": 0.12, "16-lec": 0.09, "14-alo": 0.05, "55-sai": 0.04 },
        podium: { "1-max": 0.84, "11-per": 0.72, "14-alo": 0.58, "44-ham": 0.5, "16-lec": 0.46 },
      },
      {
        modelId: "m3-form",
        winner: { "1-max": 0.49, "11-per": 0.22, "16-lec": 0.11, "44-ham": 0.09, "14-alo": 0.05, "55-sai": 0.04 },
        // The heuristic misreads the second Red Bull — Alonso misses its top three.
        podium: { "1-max": 0.86, "11-per": 0.71, "44-ham": 0.62, "14-alo": 0.58, "16-lec": 0.47 },
      },
    ],
    ensemble: {
      winner: { "1-max": 0.5, "11-per": 0.21, "16-lec": 0.1, "44-ham": 0.09, "14-alo": 0.06, "55-sai": 0.04 },
      podium: { "1-max": 0.87, "11-per": 0.71, "14-alo": 0.6, "16-lec": 0.47, "44-ham": 0.46 },
      consensus: { podiumSpread: 0.05, flag: "OK" },
    },
  },
  {
    // 2024 British GP — the spec's example record: models back Verstappen, Hamilton won.
    race: RACES[4],
    models: [
      {
        modelId: "m1-gbm",
        winner: { "1-max": 0.38, "44-ham": 0.21, "4-nor": 0.14, "63-rus": 0.12, "81-pia": 0.09, "14-alo": 0.04, "11-per": 0.02 },
        podium: { "1-max": 0.74, "44-ham": 0.61, "4-nor": 0.55, "63-rus": 0.48, "81-pia": 0.38, "11-per": 0.22 },
      },
      {
        modelId: "m2-logit",
        winner: { "1-max": 0.41, "44-ham": 0.17, "4-nor": 0.15, "63-rus": 0.12, "81-pia": 0.08, "14-alo": 0.05, "11-per": 0.02 },
        podium: { "1-max": 0.77, "4-nor": 0.58, "44-ham": 0.55, "63-rus": 0.47, "81-pia": 0.36, "11-per": 0.2 },
      },
      {
        modelId: "m3-form",
        winner: { "1-max": 0.33, "4-nor": 0.22, "44-ham": 0.15, "63-rus": 0.13, "81-pia": 0.09, "14-alo": 0.05, "11-per": 0.03 },
        podium: { "1-max": 0.69, "4-nor": 0.58, "44-ham": 0.53, "63-rus": 0.5, "81-pia": 0.37, "11-per": 0.21 },
      },
    ],
    ensemble: {
      winner: { "1-max": 0.39, "44-ham": 0.19, "4-nor": 0.15, "63-rus": 0.12, "81-pia": 0.09, "14-alo": 0.04, "11-per": 0.02 },
      podium: { "1-max": 0.74, "44-ham": 0.59, "4-nor": 0.57, "63-rus": 0.49, "81-pia": 0.37, "11-per": 0.21 },
      consensus: { podiumSpread: 0.08, flag: "OK" },
    },
  },
  {
    // 2024 United States GP — Leclerc from Sainz and Verstappen; Norris P4.
    race: RACES[5],
    models: [
      {
        modelId: "m1-gbm",
        winner: { "1-max": 0.34, "16-lec": 0.28, "4-nor": 0.16, "55-sai": 0.12, "63-rus": 0.06, "44-ham": 0.04 },
        podium: { "16-lec": 0.72, "1-max": 0.7, "55-sai": 0.62, "4-nor": 0.54, "63-rus": 0.4 },
      },
      {
        modelId: "m2-logit",
        winner: { "1-max": 0.31, "16-lec": 0.29, "4-nor": 0.18, "55-sai": 0.13, "63-rus": 0.05, "44-ham": 0.04 },
        podium: { "1-max": 0.73, "16-lec": 0.71, "55-sai": 0.6, "4-nor": 0.52, "63-rus": 0.38 },
      },
      {
        modelId: "m3-form",
        winner: { "1-max": 0.32, "16-lec": 0.27, "4-nor": 0.19, "55-sai": 0.13, "63-rus": 0.05, "44-ham": 0.04 },
        podium: { "1-max": 0.71, "16-lec": 0.7, "55-sai": 0.61, "4-nor": 0.55, "63-rus": 0.39 },
      },
    ],
    ensemble: {
      winner: { "1-max": 0.32, "16-lec": 0.28, "4-nor": 0.17, "55-sai": 0.13, "63-rus": 0.06, "44-ham": 0.04 },
      podium: { "1-max": 0.72, "16-lec": 0.7, "55-sai": 0.61, "4-nor": 0.53, "63-rus": 0.39 },
      consensus: { podiumSpread: 0.06, flag: "OK" },
    },
  },
];

export const RECORDS: PredictionRecord[] = SPECS.map(buildRecord);

export const RECORDS_BY_RACE_ID: Record<string, PredictionRecord> = Object.fromEntries(
  RECORDS.map((record) => [record.race.raceId, record]),
);

export function recordFor(raceId: string): PredictionRecord | undefined {
  return RECORDS_BY_RACE_ID[raceId];
}
