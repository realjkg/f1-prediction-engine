/**
 * TypeScript mirrors of the engine's wire schemas — the API contract the UI
 * consumes. Field names follow the engine's camelCase wire convention
 * (engine/f1engine/wire.py `to_camel`); shapes mirror:
 *
 * - PredictionRecord / RaceIdentity / DatasetIdentity — engine/f1engine/evidence.py
 * - ModelPrediction / ModelDiagnostics                — engine/f1engine/models.py
 * - EnsembleVerdict / Consensus                      — engine/f1engine/ensemble.py
 * - RaceSummary / RacesView / ModelsView / EvidencePage /
 *   ConfigView / PredictionsView / RaceResultView /
 *   CallScore                                        — engine/f1engine/app.py + scoring.py
 * - BacktestRecord / BacktestMetrics                  — engine/f1engine/evidence.py
 *
 * These are the shapes the FastAPI read surface serves (FastAPI serializes
 * response models by alias, so the wire is camelCase — engine/tests/test_api.py
 * asserts `record["advisoryOnly"]`). Live screens consume them through the
 * typed client (lib/api.ts); test fixtures mirror these shapes.
 */

/** Model roster ids — closed set, mirrors models.MODEL_IDS + the ensemble key. */
export type ModelId = "m1-gbm" | "m2-logit" | "m3-form";

/** Any scored competitor on the Model Gauntlet: the player, a model, or the ensemble. */
export type CompetitorId = "you" | ModelId | "ensemble";

export type ConsensusFlag = "OK" | "LOW_CONSENSUS";

/** engine/f1engine/evidence.py RaceIdentity */
export interface RaceIdentity {
  season: number;
  round: number;
  raceId: string;
  name: string;
}

/** engine/f1engine/evidence.py DatasetIdentity */
export interface DatasetIdentity {
  id: string;
  sha256: string;
}

/** engine/f1engine/models.py ModelDiagnostics */
export interface ModelDiagnostics {
  trainedThroughSeason: number;
  trainedThroughRound: number;
  featuresUsed: string[];
  /** null: the model has no stochastic component. */
  seed: number | null;
}

/** driver_id -> probability, exactly as the wire carries it. */
export type ProbabilityMap = Record<string, number>;

/** engine/f1engine/models.py ModelPrediction */
export interface ModelPrediction {
  raceId: string;
  modelId: ModelId;
  /** driver_id -> P(win); sums to 1 per model (engine validator). */
  winner: ProbabilityMap;
  /** driver_id -> P(top 3). */
  podium: ProbabilityMap;
  /** Snapshot provenance time — input-derived, never wall-clock. */
  generatedAt: string;
  datasetDigest: string;
  diagnostics: ModelDiagnostics;
}

/** engine/f1engine/ensemble.py Consensus */
export interface Consensus {
  podiumSpread: number;
  flag: ConsensusFlag;
}

/** engine/f1engine/ensemble.py EnsembleVerdict */
export interface EnsembleVerdict {
  raceId: string;
  winner: ProbabilityMap;
  podium: ProbabilityMap;
  consensus: Consensus;
  /** Normalized weights actually applied. */
  weightsUsed: Record<ModelId, number>;
}

/** engine/f1engine/evidence.py PredictionRecord — the shared contract. */
export interface PredictionRecord {
  schemaVersion: 1;
  recordType: "prediction";
  predictionId: string;
  race: RaceIdentity;
  generatedAt: string;
  dataset: DatasetIdentity;
  evidenceBasis: string;
  models: Record<ModelId, ModelPrediction>;
  ensemble: EnsembleVerdict;
  advisoryOnly: true;
  dataLimitations: string[];
  prevRecordSha256: string | null;
  recordSha256: string;
}

/** engine/f1engine/app.py RaceSummary — the Race screen's picker rows. */
export interface RaceSummary {
  season: number;
  round: number;
  raceId: string;
  name: string;
  date: string;
  /** Result rows for this round exist in the snapshot. */
  completed: boolean;
}

/** engine/f1engine/app.py RacesView */
export interface RacesView {
  races: RaceSummary[];
  total: number;
}

/** engine/f1engine/app.py ModelInfo */
export interface ModelInfo {
  modelId: string;
  method: string;
  role: string;
  /** The ensemble entry only. */
  consensusThreshold: number | null;
}

/** engine/f1engine/app.py ModelsView */
export interface ModelsView {
  models: ModelInfo[];
}

/** engine/f1engine/app.py EvidencePage */
export interface EvidencePageView {
  records: LedgerRecord[];
  total: number;
  offset: number;
  limit: number;
  /** Always true in a served page — a failed page is a 503. */
  chainValid: boolean;
}

/**
 * engine/f1engine/evidence.py BacktestRecord — measured accuracy as ledger
 * evidence. Same envelope rules as PredictionRecord: advisory-only,
 * self-describing, hash-chained.
 */
export interface BacktestRecord {
  schemaVersion: 1;
  recordType: "backtest";
  backtestId: string;
  season: number;
  firstRound: number;
  lastRound: number;
  roundsScored: number;
  generatedAt: string;
  dataset: DatasetIdentity;
  evidenceBasis: string;
  metricDefinitions: Record<string, string>;
  /** Keyed by MODEL_IDS + "ensemble" — closed at build time by the engine. */
  metrics: Record<string, BacktestMetrics>;
  skippedRounds: { season: number; round: number; code: string; message: string }[];
  advisoryOnly: true;
  dataLimitations: string[];
  prevRecordSha256: string | null;
  recordSha256: string;
}

/** Any record the ledger serves — prediction or backtest. */
export type LedgerRecord = PredictionRecord | BacktestRecord;

/**
 * Race identity the CLIENT keys by: the engine's predictionId format
 * ("2024-r12-british-grand-prix"). Snapshot race ids are unique per season,
 * not globally (28 of 107 repeat across years), so every client-side key and
 * every race-scoped request carries the season.
 */
export type RaceKey = string;

/** The season-qualified identity key for a race row or prediction record. */
export function raceKeyOf(season: number, round: number, raceId: string): RaceKey {
  return `${season}-r${round}-${raceId}`;
}

/** engine/f1engine/app.py EventView — already redacted at creation. */
export interface EventView {
  /** Closed signal enum (engine/f1engine/observability.py) — served as a string. */
  signal: string;
  status: string;
  occurredAt: string;
  detail: Record<string, unknown>;
}

/** engine/f1engine/app.py EventsView */
export interface EventsView {
  events: EventView[];
  total: number;
}

/** engine/f1engine/app.py ConfigView — the Settings screen's operating contract. */
export interface ConfigView {
  engineVersion: string;
  datasetVersion: string;
  advisoryOnly: boolean;
  advisoryNotice: string;
  consensusThreshold: number;
  briefMode: "fixture" | "live";
}

/** engine/f1engine/app.py PredictionsView */
export interface PredictionsView {
  predictions: PredictionRecord[];
  total: number;
}

/** engine/f1engine/app.py ClassifiedFinish */
export interface ClassifiedFinish {
  position: number;
  driverId: string;
}

/** engine/f1engine/app.py RaceResultView — the reveal's actual column. */
export interface RaceResultView {
  raceId: string;
  season: number;
  round: number;
  name: string;
  date: string;
  winner: string;
  /** Podium@3 actual — the backtest's classification (shorter on DNFs). */
  podium: string[];
  classified: ClassifiedFinish[];
}

/** engine/f1engine/scoring.py PickOutcome — closed set. */
export type PickOutcome = "EXACT" | "NEAR_MISS" | "MISS";

/** engine/f1engine/scoring.py PickCallScore */
export interface PickCallScore {
  slot: "p1" | "p2" | "p3";
  driverId: string;
  /** Classified finishing position; null = not classified (DNF, absent). */
  actualPosition: number | null;
  outcome: PickOutcome;
  points: number;
}

/** engine/f1engine/scoring.py StreakState — extension-only by design. */
export interface StreakState {
  before: number;
  after: number;
  delta: number;
  flame: boolean;
}

/** engine/f1engine/scoring.py RoundCallScore */
export interface RoundCallScore {
  picks: PickCallScore[]; // call order: p1, p2, p3
  basePoints: number;
  consensusFlag: ConsensusFlag | null;
  coinFlip: boolean;
  totalPoints: number;
}

/** engine/f1engine/scoring.py CallScore — the score endpoint's full response. */
export interface CallScore {
  round: RoundCallScore;
  streak: StreakState;
}

/** engine/f1engine/brief.py DigestPick */
export interface DigestPick {
  driverId: string;
  probability: number;
}

/** engine/f1engine/brief.py ModelDigestSummary */
export interface ModelDigestSummary {
  modelId: ModelId;
  winnerPick: DigestPick;
  winnerTop: DigestPick[];
  podiumTop: DigestPick[];
  predictionSha256: string;
  trainedThroughSeason: number;
  trainedThroughRound: number;
  seed: number | null;
}

/** engine/f1engine/brief.py QualifyingLine — grid position, never a finish. */
export interface QualifyingLine {
  driverId: string;
  position: number | null;
  qBestMs: number | null;
  deltaPoleMs: number | null;
}

/** engine/f1engine/brief.py RaceDigest */
export interface RaceDigest {
  predictionId: string;
  race: RaceIdentity;
  dataset: DatasetIdentity;
  recordSha256: string;
  ensembleWinnerTop: DigestPick[];
  ensemblePodiumTop: DigestPick[];
  consensus: Consensus;
  models: ModelDigestSummary[];
  qualifying: QualifyingLine[];
}

/** engine/f1engine/brief.py BriefContent */
export interface BriefContent {
  headline: string;
  summary: string;
  talkingPoints: string[];
  consensusNote: string;
}

/** engine/f1engine/brief.py BriefPins — live only. */
export interface BriefPins {
  datasetDigest: string;
  recordSha256: string;
  modelDigests: Record<ModelId, string>;
  ollamaModel: string;
  ollamaModelDigest: string;
}

/** engine/f1engine/brief.py RaceBrief — advisory, outside the evidence chain. */
export interface RaceBrief {
  schemaVersion: 1;
  briefType: "race-brief";
  predictionId: string;
  mode: "fixture" | "live";
  evidenceBasis: string;
  race: RaceIdentity;
  dataset: DatasetIdentity;
  digest: RaceDigest;
  content: BriefContent;
  pins: BriefPins | null;
  advisoryOnly: true;
}

/** engine/f1engine/backtest.py BacktestMetrics — the Gauntlet's metric semantics. */
export interface BacktestMetrics {
  rounds: number;
  winnerHitRate: number;
  podium3HitRate: number;
  meanBrier: number;
}

/**
 * Pit Wall game state — client-owned, localStorage-backed (design doc §7,
 * no accounts in Milestone 1). Not an engine wire type.
 */

/** The player's locked podium call, by driver id. Scored only by the engine. */
export interface RoundCall {
  p1: string;
  p2: string;
  p3: string;
  /** ISO instant of the lock — reveal-card provenance, optional in tests. */
  lockedAt?: string;
  /**
   * The dataset digest the call was made against — the same identity binding
   * the ledger uses (design doc §2, "written with the round's dataset digest").
   */
  datasetDigest?: string;
}

/** The six ship badges (design doc §5) — closed set. */
export type BadgeId =
  | "first-exact-podium"
  | "three-in-a-row"
  | "beat-the-ensemble"
  | "cold-read"
  | "data-nerd"
  | "perfect-round";

/**
 * The engine-computed summary of one locked round's score — mirrored
 * verbatim from the engine's /score response (the client never computes
 * scores). Stored per competitor on the round's lock so the Gauntlet
 * standings survive reload without recomputation.
 */
export interface RoundScoreSummary {
  positionExactCount: number;
  winnerBonus: boolean;
  nearMissCount: number;
  basePoints: number;
  coinFlip: boolean;
  totalPoints: number;
  /** The ledger's consensus flag the engine applied — null when no verdict. */
  consensusFlag: ConsensusFlag | null;
}

/**
 * The outcome of one engine-scored lock: the player's full score response
 * (picks, streak state) plus the badges the updated record earned.
 */
export interface LockOutcome {
  score: CallScore;
  badgesEarned: BadgeId[];
}

/** The pit-wall record: the player's local game state. */
export interface PitWallRecord {
  profileName: string;
  /** Locked calls by season-qualified race key (raceKeyOf) — the localStorage identity binding. */
  calls: Record<RaceKey, RoundCall>;
  /**
   * Engine-computed round scores by race key, per competitor — the standings
   * and badge inputs read from these; nothing is recomputed client-side.
   * Written only when the engine scored every competitor (atomic locks).
   */
  roundScores: Record<RaceKey, Record<CompetitorId, RoundScoreSummary>>;
  /** Consecutive rounds with at least one position-exact pick (flame at 3). */
  streak: number;
  bestStreak: number;
  badges: BadgeId[];
  /** Fresh Eyes: hide rounds already played (design doc §7). */
  freshEyes: boolean;
  /** Evidence Room opens — the Data Nerd badge counter. */
  evidenceViews: number;
}
