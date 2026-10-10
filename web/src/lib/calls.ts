/**
 * Display-side derivations over engine data — pure functions from wire types
 * to UI shapes. Nothing here scores, judges, or verifies: podium calls and
 * top picks read the engine's own distributions (descending probability,
 * driver-id tie-break — the engine's pick convention); round summaries read
 * engine-served score responses verbatim.
 */

import type {
  BacktestRecord,
  ConsensusFlag,
  DigestPick,
  LedgerRecord,
  PickCallScore,
  PredictionRecord,
  ProbabilityMap,
  RoundCall,
  RoundScoreSummary,
} from "../types";

/** A model's or ensemble's podium call: the top three of a podium distribution. */
export function podiumCall(distribution: ProbabilityMap): RoundCall | null {
  const sorted = Object.entries(distribution)
    .sort(([a, pa], [b, pb]) => pb - pa || (a < b ? -1 : 1))
    .slice(0, 3);
  if (sorted.length < 3) return null;
  const [p1, p2, p3] = sorted.map(([driverId]) => driverId);
  return { p1, p2, p3 };
}

/** Top-N picks of a probability distribution — bars and win calls. */
export function topPicks(map: ProbabilityMap, count: number): DigestPick[] {
  return Object.entries(map)
    .sort(([a, pa], [b, pb]) => pb - pa || (a < b ? -1 : 1))
    .slice(0, count)
    .map(([driverId, probability]) => ({ driverId, probability }));
}

/** Count the position-exact picks in an engine-scored round. */
export function positionExactCount(picks: PickCallScore[]): number {
  return picks.filter((pick) => pick.outcome === "EXACT").length;
}

/**
 * Fold an engine score response into the record's RoundScoreSummary — a
 * mechanical copy of engine-served numbers (counting outcomes, not scoring).
 */
export function summarizeRoundScore(round: {
  picks: PickCallScore[];
  basePoints: number;
  consensusFlag: ConsensusFlag | null;
  coinFlip: boolean;
  totalPoints: number;
}): RoundScoreSummary {
  return {
    positionExactCount: positionExactCount(round.picks),
    winnerBonus: round.picks.some((pick) => pick.slot === "p1" && pick.outcome === "EXACT"),
    nearMissCount: round.picks.filter((pick) => pick.outcome === "NEAR_MISS").length,
    basePoints: round.basePoints,
    consensusFlag: round.consensusFlag,
    coinFlip: round.coinFlip,
    totalPoints: round.totalPoints,
  };
}

/** Narrow a ledger record to its prediction half. */
export function isPredictionRecord(record: LedgerRecord): record is PredictionRecord {
  return record.recordType === "prediction";
}

/** Narrow a ledger record to its backtest half. */
export function isBacktestRecord(record: LedgerRecord): record is BacktestRecord {
  return record.recordType === "backtest";
}
