/**
 * Model Gauntlet standings (design doc §4): You vs m1-gbm / m2-logit /
 * m3-form / ensemble across the rounds the player has locked.
 *
 * Every number here was computed BY THE ENGINE at lock time — the pit-wall
 * record stores each competitor's RoundScoreSummary verbatim from
 * GET /api/races/{raceId}/score, and this module only sums and ranks them.
 * There is no client-side scoring and no fixture data: rounds without stored
 * engine scores do not exist for standings purposes.
 */

import type {
  CompetitorId,
  ConsensusFlag,
  ModelId,
  PitWallRecord,
  PredictionRecord,
  RaceKey,
  RoundCall,
  RoundScoreSummary,
} from "../types";
import { podiumCall } from "./calls";

/** All scored competitors, in display order. */
export const COMPETITORS: CompetitorId[] = [
  "you",
  "m1-gbm",
  "m2-logit",
  "m3-form",
  "ensemble",
];

export interface StandingsEntry {
  competitorId: CompetitorId;
  points: number;
  roundsPlayed: number;
  /** Position-exact podium rate across scored rounds; null before any round. */
  exactHitRate: number | null;
}

/** One round's engine-scored summaries, keyed by competitor. */
export type RoundCompetitorScores = Record<CompetitorId, RoundScoreSummary>;

/**
 * A competitor's podium call for a round: the player's lock, or the top-3 of
 * the record's podium distribution (display derivation — the ENGINE still
 * scores it). Null when the distribution cannot name three drivers.
 */
export function callForCompetitor(
  record: PredictionRecord,
  competitor: CompetitorId,
  playerCall: RoundCall | null,
): RoundCall | null {
  if (competitor === "you") return playerCall;
  const map =
    competitor === "ensemble"
      ? record.ensemble.podium
      : record.models[competitor as ModelId].podium;
  return podiumCall(map);
}

/**
 * Season standings over the locked rounds. Pure over the pit-wall record —
 * identical record, identical table.
 */
export function seasonStandings(record: PitWallRecord): StandingsEntry[] {
  const rounds = Object.entries(record.roundScores);
  const mutable = new Map<CompetitorId, { points: number; rounds: number; exact: number }>(
    COMPETITORS.map((id) => [id, { points: 0, rounds: 0, exact: 0 }]),
  );

  for (const [, scores] of rounds) {
    for (const competitor of COMPETITORS) {
      const summary = scores[competitor];
      const entry = mutable.get(competitor);
      if (!entry || !summary) continue;
      entry.points += summary.totalPoints;
      entry.rounds += 1;
      if (summary.positionExactCount === 3) entry.exact += 1;
    }
  }

  return COMPETITORS.map((competitorId) => {
    const entry = mutable.get(competitorId);
    const roundsPlayed = entry?.rounds ?? 0;
    return {
      competitorId,
      points: entry?.points ?? 0,
      roundsPlayed,
      exactHitRate: roundsPlayed > 0 ? (entry?.exact ?? 0) / roundsPlayed : null,
    };
  }).sort(
    (a, b) =>
      b.points - a.points ||
      (b.exactHitRate ?? 0) - (a.exactHitRate ?? 0) ||
      COMPETITORS.indexOf(a.competitorId) - COMPETITORS.indexOf(b.competitorId),
  );
}

/** Display names for the Gauntlet table (design doc §4). */
export const COMPETITOR_NAMES: Record<CompetitorId, string> = {
  you: "You",
  "m1-gbm": "m1-gbm",
  "m2-logit": "m2-logit",
  "m3-form": "m3-form",
  ensemble: "Ensemble",
};

/** Scored rounds with the engine-served consensus flag — the per-round chip list. */
export function playedRounds(record: PitWallRecord): {
  raceKey: RaceKey;
  flag: ConsensusFlag | null;
}[] {
  return Object.entries(record.roundScores).map(([raceKey, scores]) => ({
    raceKey,
    flag: scores.you?.consensusFlag ?? null,
  }));
}

/**
 * The season badge check: the player's total vs the ensemble's total across
 * the same scored rounds (design doc §5, "Beat The Ensemble").
 */
export function playerLeadsEnsemble(record: PitWallRecord): boolean {
  const standings = seasonStandings(record);
  const points = (id: CompetitorId) =>
    standings.find((entry) => entry.competitorId === id)?.points ?? 0;
  return points("you") > points("ensemble");
}
