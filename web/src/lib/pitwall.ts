/**
 * Pit-wall record — the player's game state for this page visit only.
 *
 * Privacy rule: nothing about the player is written to browser storage. The
 * record lives in React state and resets on reload. Earlier builds stored it
 * under one localStorage key; `purgeLegacyStorage` removes exactly that key and
 * nothing else on the origin. Scores are
 * never computed locally: a lock persists the engine's /score response per
 * competitor, and standings/badges only read those stored summaries.
 * Pre-wiring records (fixture digests, pre-season race keys) cannot be scored
 * and are dropped on load — a fresh record is the honest degradation.
 */

import type {
  CallScore,
  CompetitorId,
  PitWallRecord,
  PredictionRecord,
  RaceKey,
  RoundCall,
} from "../types";
import { badgesForRound } from "./badges";
import { seasonStandings, type RoundCompetitorScores } from "./standings";

/**
 * Keys earlier builds wrote. Only these are ever removed; unrelated storage on
 * the same origin is left alone.
 */
export const LEGACY_STORAGE_KEYS: readonly string[] = ["pitwall.record.v1"];

/** Empty record — used when nothing is stored (or storage is corrupt). */
export function emptyRecord(): PitWallRecord {
  return {
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
 * Remove the player data earlier builds persisted. Touches only the known
 * legacy keys and never throws: storage that is missing or blocked by the
 * browser simply has nothing to clean.
 */
export function purgeLegacyStorage(storage: Storage | null): string[] {
  const removed: string[] = [];
  if (!storage) return removed;
  for (const key of LEGACY_STORAGE_KEYS) {
    try {
      if (storage.getItem(key) !== null) {
        storage.removeItem(key);
        removed.push(key);
      }
    } catch {
      // Blocked storage: nothing was persisted there that we can reach.
    }
  }
  return removed;
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

/** The page's localStorage if the browser exposes it, else null (privacy modes can throw). */
export function legacyStorage(): Storage | null {
  try {
    if (typeof window !== "undefined" && window.localStorage) return window.localStorage;
  } catch {
    // Accessing window.localStorage can throw when storage is blocked.
  }
  return null;
}
