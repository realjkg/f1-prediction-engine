/**
 * Local mirror of the engine's Pit Wall scoring rules (game design doc §3,
 * spec "Game scoring" row): exact podium picks +5 each, winner bonus +3,
 * P4 near miss +1, round total 0–18, LOW_CONSENSUS rounds double the points.
 *
 * TODO(api-wiring): scoring is engine-owned — `GET /api/races/{raceId}/score`
 * will serve authoritative numbers (task todo_gFifvtGU). Until that lands,
 * this module mirrors the rules so the UI is complete on fixtures; the client
 * never *invents* scores at runtime, it only recomputes them from the same
 * published table. Swap the call site, not the math, at wiring time.
 */

import type { ConsensusFlag, ProbabilityMap, RoundCall } from "../types";

export type { RoundCall };

export const POINTS_PER_POSITION_EXACT = 5;
export const WINNER_BONUS = 3;
export const POINTS_PER_NEAR_MISS = 1;
export const COIN_FLIP_MULTIPLIER = 2;
/** 3 position-exact picks (+15) plus the winner bonus (+3). */
export const MAX_ROUND_SCORE = 18;

export interface RoundScore {
  /** Picks matching their exact finishing position (0–3). */
  positionExactCount: number;
  /** True when the P1 pick won the race. */
  winnerBonus: boolean;
  /** Picks that finished P4 — the "0.8s from the podium" heartbreak (0–1). */
  nearMissCount: number;
  /** positionExact*5 + winnerBonus*3 + nearMiss*1, before any multiplier. */
  basePoints: number;
  /** 2 on a Coin Flip Round (ensemble flag LOW_CONSENSUS), else 1. */
  multiplier: 1 | 2;
  /** basePoints * multiplier — the round's game points. */
  total: number;
  /** All three picks position-exact — winner and both podium slots. */
  perfectRound: boolean;
}

/**
 * Score one locked call against one classified finishing order.
 *
 * Pure function over published rules — the same shape the engine's
 * `GET /api/races/{raceId}/score` will serve per the design doc.
 */
export function scoreRound(
  call: RoundCall,
  finishingOrder: string[],
  consensusFlag: ConsensusFlag,
): RoundScore {
  const position = new Map<string, number>(
    finishingOrder.map((driverId, index) => [driverId, index + 1]),
  );
  const picks = [call.p1, call.p2, call.p3];
  const positionExactCount = picks.filter(
    (driverId, slot) => position.get(driverId) === slot + 1,
  ).length;
  const winnerBonus = position.get(call.p1) === 1;
  const nearMissCount = picks.filter((driverId) => position.get(driverId) === 4)
    .length;
  const basePoints =
    positionExactCount * POINTS_PER_POSITION_EXACT +
    (winnerBonus ? WINNER_BONUS : 0) +
    nearMissCount * POINTS_PER_NEAR_MISS;
  const multiplier: 1 | 2 =
    consensusFlag === "LOW_CONSENSUS" ? COIN_FLIP_MULTIPLIER : 1;
  return {
    positionExactCount,
    winnerBonus,
    nearMissCount,
    basePoints,
    multiplier,
    total: basePoints * multiplier,
    perfectRound: positionExactCount === 3,
  };
}

/**
 * Streak rule (design doc §3): "any exact podium hit extends it" — read as a
 * round containing at least one position-exact pick. The flame appears at 3.
 */
export function streakExtends(score: RoundScore): boolean {
  return score.positionExactCount >= 1;
}

/** The streak flame threshold — the record carries the count, the UI carries the flame. */
export const STREAK_FLAME_AT = 3;

/**
 * A model's or ensemble's podium call: the top three of a podium
 * distribution, descending probability with driver-id tie-break — the
 * engine's pick convention (engine/f1engine/backtest.py).
 */
export function podiumCall(distribution: ProbabilityMap): RoundCall | null {
  const sorted = Object.entries(distribution)
    .sort(([a, pa], [b, pb]) => pb - pa || (a < b ? -1 : 1))
    .slice(0, 3);
  if (sorted.length < 3) return null;
  const [p1, p2, p3] = sorted.map(([driverId]) => driverId);
  return { p1, p2, p3 };
}

/**
 * Multiclass Brier score of a winner distribution against the actual
 * winner — the engine's backtest meanBrier semantics.
 */
export function brierWinner(distribution: ProbabilityMap, winnerId: string): number {
  let total = 0;
  for (const [driverId, prob] of Object.entries(distribution)) {
    const actual = driverId === winnerId ? 1 : 0;
    total += (prob - actual) ** 2;
  }
  return total;
}
