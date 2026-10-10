/**
 * Race-brief fixtures — mirror the brief contract (engine/f1engine/brief.py
 * RaceBrief). The brief is advisory and lives OUTSIDE the evidence hash chain.
 *
 * Two modes ship so both banners are demonstrable:
 * - 2024 British GP — fixture mode (the default): DETERMINISTIC FIXTURE banner.
 * - 2021 Abu Dhabi GP — live mode: LIVE OLLAMA banner with the digest pins.
 *
 * Digest top-picks are derived from the prediction-record fixtures, so brief
 * and record can never disagree here the way engine-side derivation
 * guarantees they cannot in production.
 */

import type {
  DigestPick,
  ModelDigestSummary,
  ModelId,
  PredictionRecord,
  ProbabilityMap,
  RaceBrief,
} from "../types";
import { MOCK_GENERATED_AT } from "./drivers";
import { RECORDS_BY_RACE_ID } from "./records";
import { CALL_SHEETS } from "./callsheets";

/** Hand-authored per-model prediction digests — fixture samples. */
const FIXTURE_MODEL_DIGESTS: Record<ModelId, string> = {
  "m1-gbm":
    "b41d9c6e2a8f0357c1e6b3d8a0f4c7e29b5d1a8c3f6e0b4d7a2c5e8f1b4d6a9c",
  "m2-logit":
    "2e7c5a1f8b3d6049e1c7a3f5b9d2a6c80e4f7b1d5a3c6e9f0b2d4a7c5e1f8b3d",
  "m3-form":
    "f0a3d6c9b2e5184f7a0c3e6d9b2f5a8c1e4d7b0f3a6c9e2d5b8f1a4c7e0b3d6f",
};

const FIXTURE_OLLAMA_MODEL = "llama3.1:8b";
const FIXTURE_OLLAMA_MODEL_DIGEST =
  "9d4b7f2a5c8e1b3d6f0a4c7e2b9d5f8a1c3e6b9d2f5a8c0e3b6d9f2a5c8e1b4d";

/** Top-N picks from a distribution — descending probability, driver-id tie-break (engine convention). */
export function topPicks(map: ProbabilityMap, count: number): DigestPick[] {
  return Object.entries(map)
    .sort(([a, pa], [b, pb]) => pb - pa || (a < b ? -1 : 1))
    .slice(0, count)
    .map(([driverId, probability]) => ({ driverId, probability }));
}

function modelDigest(record: PredictionRecord, modelId: ModelId): ModelDigestSummary {
  const prediction = record.models[modelId];
  const winnerTop = topPicks(prediction.winner, 5);
  return {
    modelId,
    winnerPick: winnerTop[0],
    winnerTop,
    podiumTop: topPicks(prediction.podium, 5),
    predictionSha256: FIXTURE_MODEL_DIGESTS[modelId],
    trainedThroughSeason: prediction.diagnostics.trainedThroughSeason,
    trainedThroughRound: prediction.diagnostics.trainedThroughRound,
    seed: prediction.diagnostics.seed,
  };
}

function briefFrom(record: PredictionRecord, mode: "fixture" | "live"): RaceBrief {
  const MODEL_IDS: ModelId[] = ["m1-gbm", "m2-logit", "m3-form"];
  return {
    schemaVersion: 1,
    briefType: "race-brief",
    predictionId: record.predictionId,
    mode,
    evidenceBasis: record.evidenceBasis,
    race: record.race,
    dataset: record.dataset,
    digest: {
      predictionId: record.predictionId,
      race: record.race,
      dataset: record.dataset,
      recordSha256: record.recordSha256,
      ensembleWinnerTop: topPicks(record.ensemble.winner, 5),
      ensemblePodiumTop: topPicks(record.ensemble.podium, 5),
      consensus: record.ensemble.consensus,
      models: MODEL_IDS.map((modelId) => modelDigest(record, modelId)),
      // Grid order rides on the same call-sheet data the Race screen shows.
      qualifying: CALL_SHEETS[record.race.raceId]?.qualifying ?? [],
    },
    content:
      record.race.raceId === "british-gp"
        ? {
            headline: "Silverstone brings rain, and the models lean Verstappen",
            summary:
              "The ensemble gives Max Verstappen a 0.39 win probability, its strongest pick of the fixture set. " +
              "Home crowds want Hamilton, and the call sheet says the Mercedes has been quick in race trim all weekend — " +
              "but the machine prices that at 0.19. Norris rounds out the podium picks from P3 on the grid.",
            talkingPoints: [
              "Verstappen has led every lap of the fixture's recent rounds — the field's form lines point one way.",
              "Russell starts P1 on the grid yet is only the ensemble's fourth pick: track history outweighs Saturday.",
              "A podium call of Verstappen-Hamilton-Norris matches the podium distribution's top three, order aside.",
            ],
            consensusNote:
              "Models agree: podium spread 0.08 is well inside the 0.15 consensus band. No coin-flip bonus this round.",
          }
        : {
            headline: "Abu Dhabi splits the machine — the title coin flip",
            summary:
              "The models cannot agree: m1-gbm and m3-form lean Verstappen, m2-logit backs Hamilton, and podium " +
              "spread 0.19 blows past the 0.15 consensus band. The ensemble lands on Verstappen by a whisker (0.42 to 0.38) " +
              "and flags the round LOW_CONSENSUS — on the pit wall, that makes it a coin-flip round: points double.",
            talkingPoints: [
              "m2-logit is the dissenting voice: its winner pick is Hamilton at 0.42, against both other models.",
              "Every model's podium call carries the same three drivers — the disagreement is strictly about the order.",
              "Grid positions one and two belong to the contenders; form lines cannot separate them either.",
            ],
            consensusNote:
              "LOW_CONSENSUS: podium spread 0.19 exceeds the 0.15 threshold. Flagged, never suppressed — points double.",
          },
    pins:
      mode === "live"
        ? {
            datasetDigest: record.dataset.sha256,
            recordSha256: record.recordSha256,
            modelDigests: { ...FIXTURE_MODEL_DIGESTS },
            ollamaModel: FIXTURE_OLLAMA_MODEL,
            ollamaModelDigest: FIXTURE_OLLAMA_MODEL_DIGEST,
          }
        : null,
    advisoryOnly: true,
  };
}

// Fixture briefs for two of the six sample rounds — the picker exposes the gap.
export const BRIEFS: Record<string, RaceBrief> = {
  "british-gp": briefFrom(RECORDS_BY_RACE_ID["british-gp"], "fixture"),
  "abu-dhabi-gp": briefFrom(RECORDS_BY_RACE_ID["abu-dhabi-gp"], "live"),
};

export function briefFor(raceId: string): RaceBrief | undefined {
  return BRIEFS[raceId];
}

export const BRIEF_FIXTURE_BANNER = "DETERMINISTIC FIXTURE — NO LOCAL MODEL INFERENCE";
export const BRIEF_LIVE_BANNER = "LIVE OLLAMA BRIEF — DIGEST-PINNED — TEMPERATURE 0";

/** Display provenance for the brief screen (generatedAt mirrors the dataset, not the clock). */
export const BRIEF_GENERATED_AT = MOCK_GENERATED_AT;
