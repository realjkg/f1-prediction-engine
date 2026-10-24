/**
 * A mocked engine for screen tests: response fixtures that match the real
 * pydantic wire shapes (engine/f1engine/app.py, camelCase on the wire) and a
 * fetch router serving them. The /score handler mirrors the engine's
 * published scoring table (engine/f1engine/scoring.py) the same way the
 * engine's own tests do — the CLIENT never scores, so the screens under
 * test only ever render the mocked responses' numbers.
 */

import type {
  BacktestRecord,
  CallScore,
  ConfigView,
  ConsensusFlag,
  EventsView,
  ModelsView,
  PickCallScore,
  PredictionRecord,
  ProbabilityMap,
  RaceResultView,
  RacesView,
  RoundCall,
  CatalogRace,
  DataQualityReport,
  ModelEvaluationView,
  PredictionCatalogView,
  PredictionEnvelope,
} from "../types";

export const CONFIG: ConfigView = {
  engineVersion: "0.1.0",
  datasetVersion: "test.2024",
  advisoryOnly: true,
  advisoryNotice: "Predictions are advisory — always call your own race.",
  consensusThreshold: 0.15,
  briefMode: "fixture",
};

export const RACES: RacesView = {
  races: [
    {
      season: 2024,
      round: 1,
      raceId: "bahrain-gp",
      name: "Bahrain Grand Prix",
      date: "2024-03-02",
      completed: true,
    },
    {
      season: 2024,
      round: 2,
      raceId: "saudi-arabia-gp",
      name: "Saudi Arabian Grand Prix",
      date: "2024-03-09",
      completed: true,
    },
  ],
  total: 2,
};

/** Bahrain 2024's classified top five. */
const BAHRAIN_PODIUM = ["max_verstappen", "leclerc", "perez"];
const BAHRIAN_CLASSIFIED = [
  { position: 1, driverId: "max_verstappen" },
  { position: 2, driverId: "leclerc" },
  { position: 3, driverId: "perez" },
  { position: 4, driverId: "russell" },
  { position: 5, driverId: "hamilton" },
];

/** Saudi Arabia 2024's classified top five. */
const SAUDI_PODIUM = ["max_verstappen", "perez", "leclerc"];
const SAUDI_CLASSIFIED = [
  { position: 1, driverId: "max_verstappen" },
  { position: 2, driverId: "perez" },
  { position: 3, driverId: "leclerc" },
  { position: 4, driverId: "russell" },
  { position: 5, driverId: "hamilton" },
];

function predictionRecord(
  raceId: string,
  name: string,
  round: number,
  winner: ProbabilityMap,
  podium: ProbabilityMap,
  flag: ConsensusFlag,
  spread: number,
): PredictionRecord {
  const dataset = { id: "test.2024", sha256: "a".repeat(64) };
  const models = {
    "m1-gbm": { winner, podium },
    "m2-logit": { winner, podium },
    "m3-form": { winner, podium },
  } as const;
  const modelPredictions = Object.fromEntries(
    Object.entries(models).map(([modelId, distributions]) => [
      modelId,
      {
        raceId,
        modelId,
        winner: distributions.winner,
        podium: distributions.podium,
        generatedAt: "2024-03-01T00:00:00Z",
        datasetDigest: dataset.sha256,
        diagnostics: {
          trainedThroughSeason: 2023,
          trainedThroughRound: 22,
          featuresUsed: ["form", "qualifying"],
          seed: modelId === "m1-gbm" ? 42 : null,
        },
      },
    ]),
  ) as PredictionRecord["models"];
  return {
    schemaVersion: 1,
    recordType: "prediction",
    predictionId: `2024-r${round}-${raceId}`,
    race: { season: 2024, round, raceId, name },
    generatedAt: "2024-03-01T00:00:00Z",
    dataset,
    evidenceBasis: "REAL MODELS — PINNED DATASET 2020–2024 — TEST FIXTURE",
    models: modelPredictions,
    ensemble: {
      raceId,
      winner,
      podium,
      consensus: { podiumSpread: spread, flag },
      weightsUsed: { "m1-gbm": 0.5, "m2-logit": 0.3, "m3-form": 0.2 },
    },
    advisoryOnly: true,
    dataLimitations: ["no in-race telemetry in the pinned window"],
    prevRecordSha256: null,
    recordSha256: "b".repeat(64),
  };
}

const BAHRAIN_RECORD = predictionRecord(
  "bahrain-gp",
  "Bahrain Grand Prix",
  1,
  { max_verstappen: 0.38, leclerc: 0.21, perez: 0.14, hamilton: 0.1, norris: 0.09 },
  { max_verstappen: 0.74, leclerc: 0.61, perez: 0.55, hamilton: 0.4, norris: 0.35 },
  "OK",
  0.08,
);

const SAUDI_RECORD = predictionRecord(
  "saudi-arabia-gp",
  "Saudi Arabian Grand Prix",
  2,
  { max_verstappen: 0.3, leclerc: 0.24, perez: 0.23, hamilton: 0.12, norris: 0.1 },
  { max_verstappen: 0.52, leclerc: 0.5, perez: 0.49, hamilton: 0.38, norris: 0.34 },
  "LOW_CONSENSUS",
  0.27,
);

export const RESULTS: Record<string, RaceResultView> = {
  "bahrain-gp": {
    raceId: "bahrain-gp",
    season: 2024,
    round: 1,
    name: "Bahrain Grand Prix",
    date: "2024-03-02",
    winner: "max_verstappen",
    podium: BAHRAIN_PODIUM,
    classified: BAHRIAN_CLASSIFIED,
  },
  "saudi-arabia-gp": {
    raceId: "saudi-arabia-gp",
    season: 2024,
    round: 2,
    name: "Saudi Arabian Grand Prix",
    date: "2024-03-09",
    winner: "max_verstappen",
    podium: SAUDI_PODIUM,
    classified: SAUDI_CLASSIFIED,
  },
};

export const MODELS: ModelsView = {
  models: [
    { modelId: "m1-gbm", method: "gradient-boosted trees", role: "the ML voice", consensusThreshold: null },
    { modelId: "m2-logit", method: "logistic regression", role: "interpretable counterweight", consensusThreshold: null },
    { modelId: "m3-form", method: "rolling-form heuristic", role: "sanity floor", consensusThreshold: null },
    { modelId: "ensemble", method: "weighted blend", role: "adjudicated verdict", consensusThreshold: 0.15 },
  ],
};

export const BACKTEST: BacktestRecord = {
  schemaVersion: 1,
  recordType: "backtest",
  backtestId: "2024-backtest",
  season: 2024,
  firstRound: 1,
  lastRound: 2,
  roundsScored: 2,
  generatedAt: "2024-03-10T00:00:00Z",
  dataset: { id: "test.2024", sha256: "a".repeat(64) },
  evidenceBasis: "REAL MODELS — EXPANDING WINDOW — TEST FIXTURE",
  metricDefinitions: { winnerHitRate: "share of rounds whose top pick won" },
  metrics: {
    "m1-gbm": { rounds: 2, winnerHitRate: 0.5, podium3HitRate: 1, meanBrier: 0.21 },
    ensemble: { rounds: 2, winnerHitRate: 0.5, podium3HitRate: 1, meanBrier: 0.19 },
  },
  skippedRounds: [{ season: 2024, round: 3, code: "QUALI_MISSING", message: "no qualifying rows" }],
  advisoryOnly: true,
  dataLimitations: ["fixture window"],
  prevRecordSha256: BAHRAIN_RECORD.recordSha256,
  recordSha256: "c".repeat(64),
};

export const EVIDENCE_PAGE = {
  records: [BAHRAIN_RECORD, SAUDI_RECORD, BACKTEST],
  total: 3,
  offset: 0,
  limit: 100,
  chainValid: true,
};

export const EVENTS: EventsView = {
  events: [
    {
      signal: "PREDICTION_WRITTEN",
      status: "OK",
      occurredAt: "2024-03-01T00:00:00Z",
      detail: { raceId: "bahrain-gp" },
    },
  ],
  total: 1,
};

export const METRICS_TEXT =
  '# HELP f1engine_predictions_total Predictions written\n# TYPE f1engine_predictions_total counter\nf1engine_predictions_total 24\n';

/** A podium call derived the way the engine orders picks: descending probability. */
export function podiumCallOf(distribution: ProbabilityMap): RoundCall {
  const top = Object.entries(distribution)
    .sort(([a, pa], [b, pb]) => pb - pa || (a < b ? -1 : 1))
    .slice(0, 3)
    .map(([driverId]) => driverId);
  if (top.length < 3) throw new Error("fixture distribution too thin");
  return { p1: top[0], p2: top[1], p3: top[2] };
}

/** The engine's scoring table (engine/f1engine/scoring.py), for mock /score. */
function scoreCall(
  raceId: string,
  call: RoundCall,
  streakBefore: number,
): CallScore {
  const record = raceId === "bahrain-gp" ? BAHRAIN_RECORD : SAUDI_RECORD;
  const result = RESULTS[raceId];
  const flag = record.ensemble.consensus.flag;
  const positionOf = new Map(result.classified.map((f) => [f.driverId, f.position]));
  const picks: PickCallScore[] = (["p1", "p2", "p3"] as const).map((slot, index) => {
    const driverId = call[slot];
    const actualPosition = positionOf.get(driverId) ?? null;
    const outcome: PickCallScore["outcome"] =
      actualPosition === index + 1 ? "EXACT" : actualPosition === 4 ? "NEAR_MISS" : "MISS";
    return {
      slot,
      driverId,
      actualPosition,
      outcome,
      points: outcome === "EXACT" ? 5 : outcome === "NEAR_MISS" ? 1 : 0,
    };
  });
  const basePoints = picks.reduce((sum, pick) => sum + pick.points, 0);
  const winnerBonus = picks[0].outcome === "EXACT" ? 3 : 0;
  const withBonus = basePoints + winnerBonus;
  const coinFlip = flag === "LOW_CONSENSUS";
  const delta = picks.some((pick) => pick.outcome === "EXACT") ? 1 : 0;
  return {
    round: {
      picks,
      basePoints: withBonus,
      consensusFlag: flag,
      coinFlip,
      totalPoints: coinFlip ? withBonus * 2 : withBonus,
    },
    streak: { before: streakBefore, after: streakBefore + delta, delta, flame: streakBefore + delta >= 3 },
  };
}

export interface MockEngine {
  /** Every request path the app made, in order. */
  requests: string[];
  /** Make every subsequent fetch reject — the engine-unreachable state. */
  failAll: () => void;
  /** Restore normal serving. */
  serve: () => void;
  /** Put the mock back the way vitest's environment had it. */
  restore: () => void;
}

/**
 * Install the mock over globalThis.fetch. jsdom's window.fetch shadows
 * Node's — override both so the app's same-origin client hits the mock.
 */
/* ---- pre-race prediction contracts (engine/f1engine/prediction_api.py) ---- */

const checkpoints = (supported: boolean, reason: string | null): CatalogRace["checkpoints"] => [
  { checkpoint: "pre-weekend", supported, reason },
  {
    checkpoint: "post-qualifying",
    supported: false,
    reason: "The models read only rounds before the race, not that race's own qualifying.",
  },
];

export const CATALOG: PredictionCatalogView = {
  races: [
    {
      raceId: "saudi-arabia-gp", season: 2024, round: 2, name: "Saudi Arabian Grand Prix",
      raceDate: "2024-03-09", circuitName: "Jeddah Corniche Circuit", country: "Saudi Arabia",
      status: "completed", predictionMode: "historical-backtest", checkpoints: checkpoints(true, null),
    },
    {
      raceId: "bahrain-gp", season: 2024, round: 1, name: "Bahrain Grand Prix",
      raceDate: "2024-03-02", circuitName: "Bahrain International Circuit", country: "Bahrain",
      status: "completed", predictionMode: "historical-backtest", checkpoints: checkpoints(true, null),
    },
    {
      raceId: "austrian-grand-prix", season: 2020, round: 1, name: "Austrian Grand Prix",
      raceDate: "2020-07-05", circuitName: "Red Bull Ring", country: "Austria",
      status: "completed", predictionMode: "unavailable",
      checkpoints: checkpoints(false, "No prediction record for this round in the evidence ledger."),
    },
  ],
  total: 3,
  supportedTotal: 2,
  datasetId: "test.2024",
  datasetDigest: "a".repeat(64),
  dataThroughDate: "2024-03-09",
  upcomingRaces: 0,
  upcomingNote: "No upcoming races are in the pinned data.",
  advisoryOnly: true,
};

const FEATURE_LABELS = {
  form_finish_mean: "Average finish, last five rounds",
  team_points_mean: "Team points per round, prior rounds",
};

export function predictionEnvelope(raceId: string): PredictionEnvelope {
  const race = CATALOG.races.find((entry) => entry.raceId === raceId)!;
  const record = raceId === "saudi-arabia-gp" ? SAUDI_RECORD : BAHRAIN_RECORD;
  const teams: Record<string, string> = { max_verstappen: "Red Bull", perez: "Red Bull", leclerc: "Ferrari", sainz: "Ferrari" };
  const ordered = Object.entries(record.ensemble.winner).sort((a, b) => b[1] - a[1]);
  return {
    raceId, season: race.season, round: race.round, raceName: race.name, raceDate: race.raceDate,
    circuitName: race.circuitName, country: race.country, session: "race",
    predictionMode: "historical-backtest", checkpoint: "pre-weekend",
    predictionGeneratedAt: null, evidenceGeneratedAt: "2024-03-01T00:00:00Z",
    featureCutoff: {
      throughSeason: 2023, throughRound: 22, throughRaceName: "Abu Dhabi Grand Prix",
      throughRaceDate: "2023-11-26",
      excludes: ["This race's practice, qualifying, grid and penalties", "This race's result and anything later"],
    },
    sourceUpdatedAt: "2026-10-09T22:59:52+00:00", fetchedAt: "2026-10-23T12:00:00+00:00",
    freshness: "historical", freshnessNote: "Replayed from data retrieved 2026-10-09. This race is finished.",
    modelRevision: "m1-gbm+m2-logit+m3-form@seed-2026", models: ["m1-gbm", "m2-logit", "m3-form"],
    datasetId: "test.2024", datasetDigest: "a".repeat(64), evidencePredictionId: record.predictionId,
    provenance: [{ provider: "jolpica-f1", role: "results", fetchedAt: "2026-10-09T22:59:52+00:00", license: "CC-BY-NC-SA-4.0" }],
    outputs: [
      { output: "winner", supported: true, reason: "Ensemble of three models; sums to 1 across the field." },
      { output: "podium", supported: false, reason: "Stored podium values do not add up to three podium places." },
      { output: "points", supported: false, reason: "No points model has been trained." },
    ],
    drivers: ordered.map(([driverId, probability], index) => ({
      driverId,
      driverName: driverId === "max_verstappen" ? "Max Verstappen" : driverId[0].toUpperCase() + driverId.slice(1),
      driverCode: driverId.slice(0, 3).toUpperCase(),
      constructorId: (teams[driverId] ?? "team").toLowerCase().replace(" ", "_"),
      constructorName: teams[driverId] ?? "Team",
      rank: index + 1,
      winProbability: probability,
      perModelWinProbability: { "m1-gbm": probability, "m2-logit": probability, "m3-form": probability },
      features: { form_finish_mean: index + 1.5, team_points_mean: index === 3 ? null : 30 - index },
      reasons: index === 0 ? ["Ranks 1 of 4 on average finish, last five rounds (1.5)."] : [],
    })),
    featureLabels: FEATURE_LABELS,
    consensusFlag: record.ensemble.consensus.flag,
    baseline: { name: "Blind guess", winProbability: 1 / ordered.length, detail: `Picking any of the ${ordered.length} entrants at random.` },
    missingInputs: [
      { input: "Weather forecast", status: "not-in-dataset", detail: "No forecast weather is stored.", sourceNeeded: "An archived pre-race forecast provider" },
    ],
    limitations: ["no in-race telemetry in the pinned window"],
    validation: [
      { check: "ensemble winner probabilities sum to 1", passed: true, detail: "sum = 1.000000" },
      { check: "podium probabilities sum to about 3", passed: false, detail: "ensemble sum = 2.54" },
    ],
    outcomeAvailable: true,
    advisoryOnly: true,
  };
}

const estimate = (value: number) => ({ value, ciLow: value * 0.8, ciHigh: value * 1.2 });

export const EVALUATION: ModelEvaluationView = {
  cohort: "2024 season prediction records", method: "Walk-forward.", rounds: 2, season: 2024,
  scores: ["m1-gbm", "m2-logit", "m3-form", "ensemble"].map((modelId) => ({
    modelId, rounds: 2, winnerHitRate: estimate(0.5), winnerLogLoss: estimate(1.2),
    winnerBrier: estimate(0.6), meanProbabilityOnWinner: 0.4,
  })),
  baseline: {
    modelId: "blind-guess", rounds: 2, winnerHitRate: estimate(0.25), winnerLogLoss: estimate(1.39),
    winnerBrier: estimate(0.75), meanProbabilityOnWinner: 0.25,
  },
  calibrationModel: "ensemble",
  calibration: [{ lower: 0, upper: 0.05, predictions: 4, meanPredicted: 0.02, observedWinRate: 0 }],
  calibrationVerdict: "Not established: only 2 race winners.",
  caveats: ["2 races is a small sample; the 95% intervals are wide."],
  bootstrapResamples: 200, bootstrapSeed: 2026, advisoryOnly: true,
};

export const DATA_QUALITY: DataQualityReport = {
  datasetId: "test.2024", datasetDigest: "a".repeat(64), sourceUpdatedAt: "2026-10-09T22:59:52+00:00",
  checkedAt: "2026-10-23T12:00:00+00:00", sourceAgeDays: 14,
  dataThroughDate: "2024-03-09", coverageLagDays: 958,
  coverage: [{ season: 2024, races: 2, roundsWithResults: 2, roundsWithQualifying: 2, predictionRecords: 2 }],
  findings: [
    { check: "referential integrity", severity: "info", passed: true, affected: 0, detail: "All rows resolve.", examples: [], blocksTraining: false, blocksInference: false },
    { check: "podium probabilities sum to about 3", severity: "warning", passed: false, affected: 1, detail: "Podium withheld.", examples: ["2024-1: 2.54"], blocksTraining: false, blocksInference: false },
  ],
  trainingBlocked: false, inferenceBlocked: false, summary: "No blocking problems. 1 check(s) need attention.",
};

export function installMockEngine(): MockEngine {
  const requests: string[] = [];
  let failing = false;
  const original = globalThis.fetch;

  const jsonResponse = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });

  const route = (url: string): Response => {
    // Split path from query with the URL parser — raceIds and season params
    // must not smear into each other (the client season-qualifies requests).
    const parsed = new URL(url, "http://test");
    const path = parsed.pathname;
    const parts = path.split("/"); // e.g. ["", "api", "races", "bahrain-gp", "score"]
    if (path.startsWith("/api/config")) return jsonResponse(CONFIG);
    if (path === "/api/prediction-catalog") return jsonResponse(CATALOG);
    if (path === "/api/model-evaluation") return jsonResponse(EVALUATION);
    if (path === "/api/data-quality") return jsonResponse(DATA_QUALITY);
    if (parts[2] === "races" && parts[4] === "prediction") {
      const raceId = parts[3] ?? "";
      const race = CATALOG.races.find((entry) => entry.raceId === raceId);
      if (!race) return jsonResponse({ detail: { code: "RACE_UNKNOWN", message: "unknown race" } }, 404);
      if (parsed.searchParams.get("checkpoint") === "post-qualifying") {
        return jsonResponse({ detail: { code: "CHECKPOINT_UNSUPPORTED", message: "not supported" } }, 409);
      }
      if (race.predictionMode === "unavailable") {
        return jsonResponse({ detail: { code: "PREDICTION_UNAVAILABLE", message: "no record" } }, 404);
      }
      return jsonResponse(predictionEnvelope(raceId));
    }
    if (path === "/api/live/status") return jsonResponse({
      feedState: "not-configured", evidenceState: "none",
      inferenceState: "unavailable", season: Number(parsed.searchParams.get("season") ?? 2026),
      raceId: parsed.searchParams.get("race_id") ?? "singapore", broker: "openf1",
      lastMessageAt: null, lastCheckpointAt: null, lap: null, totalLaps: null,
      sourceType: null, checkpointSha256: null, qualifiedForProduction: false,
      modelPromoted: false,
    });
    if (parts[2] === "races" && parts[4] === "score") {
      const raceId = parts[3] ?? "";
      const callParts = (parsed.searchParams.get("call") ?? ",").split(",");
      const call: RoundCall = { p1: callParts[0], p2: callParts[1], p3: callParts[2] };
      const streakBefore = Number.parseInt(parsed.searchParams.get("streak_before") ?? "0", 10);
      return jsonResponse(scoreCall(raceId, call, streakBefore));
    }
    if (parts[2] === "races" && parts[4] === "result") {
      const result = RESULTS[parts[3] ?? ""];
      return result
        ? jsonResponse(result)
        : jsonResponse(
            { detail: { code: "RESULT_NOT_FOUND", message: "no classified result" } },
            404,
          );
    }
    if (parts[2] === "predictions") {
      const raceId = decodeURIComponent(parts[3] ?? "");
      const record = raceId === "bahrain-gp" ? BAHRAIN_RECORD : raceId === "saudi-arabia-gp" ? SAUDI_RECORD : null;
      return record
        ? jsonResponse({ predictions: [record], total: 1 })
        : jsonResponse(
            { detail: { code: "PREDICTIONS_NOT_FOUND", message: "no record" } },
            404,
          );
    }
    if (path.startsWith("/api/races")) return jsonResponse(RACES);
    if (path.startsWith("/api/models")) return jsonResponse(MODELS);
    if (path.startsWith("/api/evidence")) return jsonResponse(EVIDENCE_PAGE);
    if (path.startsWith("/api/events")) return jsonResponse(EVENTS);
    if (path.startsWith("/metrics")) return new Response(METRICS_TEXT, { status: 200 });
    return jsonResponse({ detail: { code: "RESPONSE_NOT_OK", message: `unrouted ${path}` } }, 404);
  };

  const mockFetch: typeof fetch = (input, _init) => {
    const url = String(input instanceof Request ? input.url : input);
    requests.push(url);
    if (failing) {
      return Promise.reject(new TypeError("Failed to fetch"));
    }
    return Promise.resolve(route(url));
  };

  globalThis.fetch = mockFetch;
  (window as unknown as { fetch: typeof fetch }).fetch = mockFetch;

  return {
    requests,
    failAll: () => {
      failing = true;
    },
    serve: () => {
      failing = false;
    },
    restore: () => {
      globalThis.fetch = original;
      (window as unknown as { fetch: typeof fetch }).fetch = original;
    },
  };
}
