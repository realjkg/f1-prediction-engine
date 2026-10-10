/**
 * Pit-wall record — the player's local game state. localStorage-backed.
 *
 * Calls and round scores live here in Milestone 1 (no accounts). Scores are
 * never computed locally: a lock persists the engine's /score response per
 * competitor, and standings/badges only read those stored summaries.
 * Pre-wiring records (fixture digests, pre-season race keys) cannot be scored
 * and are dropped on load — a fresh record is the honest degradation.
 */

import type {
  BadgeId,
  CallScore,
  CompetitorId,
  ConsensusFlag,
  PitWallRecord,
  PredictionRecord,
  RaceKey,
  RoundCall,
  RoundScoreSummary,
} from "../types";
import { badgesForRound } from "./badges";
import { seasonStandings, type RoundCompetitorScores } from "./standings";

const STORAGE_KEY = "pitwall.record.v1";

const VALID_BADGES: BadgeId[] = [
  "first-exact-podium",
  "three-in-a-row",
  "beat-the-ensemble",
  "cold-read",
  "data-nerd",
  "perfect-round",
];

/** Empty record — used when nothing is stored (or storage is corrupt). */
export function emptyRecord(): PitWallRecord {
  return {
    profileName: "",
    calls: {},
    roundScores: {},
    streak: 0,
    bestStreak: 0,
    badges: [],
    freshEyes: false,
    evidenceViews: 0,
  };
}

/**
 * Read the record; falls back to empty on missing or malformed JSON.
 * Storage corruption must never brick the app — degrade to a fresh record.
 */
export function loadRecord(storage: Storage | null): PitWallRecord {
  if (!storage) return emptyRecord();
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return emptyRecord();
    return hydrate(JSON.parse(raw));
  } catch {
    // Corrupt record — start clean rather than crash or silently drop writes.
    return emptyRecord();
  }
}

/**
 * Validate an unknown stored shape into a PitWallRecord. Unknown fields are
 * dropped; missing fields get defaults. Hand-rolled rather than zod to keep
 * the bundle lean — the shape is ours, not external.
 */
export function hydrate(parsed: unknown): PitWallRecord {
  const base = emptyRecord();
  if (typeof parsed !== "object" || parsed === null) return base;
  const raw = parsed as Record<string, unknown>;

  const badges: BadgeId[] = Array.isArray(raw.badges)
    ? raw.badges.filter((b): b is BadgeId => VALID_BADGES.includes(b as BadgeId))
    : [];

  // Round scores are the engine's numbers, kept verbatim; a stored entry
  // without a matching call is orphaned and dropped.
  const roundScores: PitWallRecord["roundScores"] = {};
  if (typeof raw.roundScores === "object" && raw.roundScores !== null) {
    for (const [raceKey, value] of Object.entries(
      raw.roundScores as Record<string, unknown>,
    )) {
      const scores = hydrateRoundScores(value);
      if (scores) roundScores[raceKey] = scores;
    }
  }

  // Rounds without a stored engine score cannot be displayed honestly —
  // drop the call rather than show an unscored round.
  const calls: PitWallRecord["calls"] = {};
  if (typeof raw.calls === "object" && raw.calls !== null) {
    for (const [raceKey, value] of Object.entries(
      raw.calls as Record<string, unknown>,
    )) {
      if (!(raceKey in roundScores)) continue;
      const call = hydrateCall(value);
      if (call) calls[raceKey] = call;
    }
  }

  return {
    profileName:
      typeof raw.profileName === "string" ? raw.profileName : base.profileName,
    calls,
    roundScores,
    streak: typeof raw.streak === "number" ? raw.streak : 0,
    bestStreak: typeof raw.bestStreak === "number" ? raw.bestStreak : 0,
    badges,
    freshEyes: raw.freshEyes === true,
    evidenceViews: typeof raw.evidenceViews === "number" ? raw.evidenceViews : 0,
  };
}

const COMPETITOR_IDS = [
  "you",
  "m1-gbm",
  "m2-logit",
  "m3-form",
  "ensemble",
] as const;

/** Validate one round's per-competitor score block; incomplete blocks drop. */
function hydrateRoundScores(value: unknown): PitWallRecord["roundScores"][string] | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const raw = value as Record<string, unknown>;
  const scores: Partial<Record<CompetitorId, RoundScoreSummary>> = {};
  for (const competitor of COMPETITOR_IDS) {
    const summary = hydrateSummary(raw[competitor]);
    if (!summary) return undefined; // All five competitors or none — atomic.
    scores[competitor] = summary;
  }
  return scores as Record<CompetitorId, RoundScoreSummary>;
}

function hydrateSummary(value: unknown): RoundScoreSummary | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const raw = value as Record<string, unknown>;
  if (typeof raw.totalPoints !== "number" || typeof raw.basePoints !== "number") {
    return undefined;
  }
  const flag = raw.consensusFlag;
  return {
    positionExactCount:
      typeof raw.positionExactCount === "number" ? raw.positionExactCount : 0,
    winnerBonus: raw.winnerBonus === true,
    nearMissCount: typeof raw.nearMissCount === "number" ? raw.nearMissCount : 0,
    basePoints: raw.basePoints,
    coinFlip: raw.coinFlip === true,
    totalPoints: raw.totalPoints,
    consensusFlag:
      flag === "OK" || flag === "LOW_CONSENSUS" ? (flag as ConsensusFlag) : null,
  };
}

function hydrateCall(value: unknown): RoundCall | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const raw = value as Record<string, unknown>;
  const { p1, p2, p3 } = raw;
  if (typeof p1 !== "string" || typeof p2 !== "string" || typeof p3 !== "string") {
    return undefined;
  }
  const lockedAt = typeof raw.lockedAt === "string" ? raw.lockedAt : undefined;
  const datasetDigest =
    typeof raw.datasetDigest === "string" ? raw.datasetDigest : undefined;
  return { p1, p2, p3, lockedAt, datasetDigest };
}

/** Persist the record; storage failures are surfaced, never swallowed. */
export function saveRecord(storage: Storage | null, record: PitWallRecord): void {
  if (!storage) {
    throw new Error("STORAGE_UNAVAILABLE — cannot persist pit-wall record");
  }
  storage.setItem(STORAGE_KEY, JSON.stringify(record));
}

/** Test seam: clear the stored record. */
export function clearRecord(storage: Storage | null): void {
  storage?.removeItem(STORAGE_KEY);
}

/**
 * Fold one engine-scored lock into the record — pure, the single write path
 * for game state. Every number arrives from the engine (score responses per
 * competitor); badges are re-evaluated over the UPDATED record so season
 * totals include this round.
 */
export function applyLockedRound(
  current: PitWallRecord,
  raceKey: RaceKey,
  call: RoundCall,
  scores: RoundCompetitorScores,
  playerScore: CallScore,
  predictionRecord: PredictionRecord,
): PitWallRecord {
  const base: PitWallRecord = {
    ...current,
    calls: { ...current.calls, [raceKey]: call },
    roundScores: { ...current.roundScores, [raceKey]: scores },
    streak: playerScore.streak.after,
    bestStreak: Math.max(current.bestStreak, playerScore.streak.after),
  };
  const standings = seasonStandings(base);
  const points = (competitor: CompetitorId) =>
    standings.find((entry) => entry.competitorId === competitor)?.points ?? 0;
  const onPodium = (slot: "p2" | "p3"): boolean => {
    const pick = playerScore.round.picks.find((p) => p.slot === slot);
    return pick?.actualPosition != null && pick.actualPosition <= 3;
  };
  const earned = badgesForRound({
    exactPodium: scores.you.positionExactCount === 3,
    winnerCalled: scores.you.winnerBonus,
    winnerProb: predictionRecord.ensemble.winner[call.p1] ?? null,
    p2OnPodium: onPodium("p2"),
    p3OnPodium: onPodium("p3"),
    streakAfterRound: playerScore.streak.after,
    playerPoints: points("you"),
    ensemblePoints: points("ensemble"),
    evidenceViews: base.evidenceViews,
  });
  return { ...base, badges: [...new Set([...base.badges, ...earned])] };
}

/**
 * Browser storage accessor. Environments without accessible localStorage
 * (SSR, privacy modes that throw) get a memory shim so the UI still runs —
 * those writes are lost on reload, which is the honest degradation.
 */
export function browserStorage(): Storage {
  try {
    if (typeof window !== "undefined" && window.localStorage) return window.localStorage;
  } catch {
    // window.localStorage can throw in privacy modes — fall through.
  }
  return memoryStorage();
}

function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key: string) => map.get(key) ?? null,
    key: (index: number) => Array.from(map.keys())[index] ?? null,
    removeItem: (key: string) => {
      map.delete(key);
    },
    setItem: (key: string, value: string) => {
      map.set(key, value);
    },
  };
}
