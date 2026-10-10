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
