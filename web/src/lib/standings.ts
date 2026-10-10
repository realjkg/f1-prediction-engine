/**
 * Model Gauntlet standings (design doc §4): You vs m1-gbm / m2-logit /
 * m3-form / ensemble across the rounds the player has locked.
 *
 * Fixture-level mirror of the engine's backtest semantics: model podium
 * calls are the top-3 of the podium distribution (descending probability,
 * driver-id tie-break — the engine's pick convention), and mean Brier is the
 * multiclass winner-distribution score. TODO(api-wiring): the engine's
 * backtest + score endpoints are authoritative (todo_gFifvtGU); swap the
 * data source, not this display logic, at wiring time.
 */

import type {
  CompetitorId,
  ConsensusFlag,
  ModelId,
  PitWallRecord,
  PredictionRecord,
  ProbabilityMap,
  RaceSummary,
  RoundCall,
} from "../types";
import { CALL_SHEETS, type CallSheet } from "../fixtures/callsheets";
import { RECORDS_BY_RACE_ID } from "../fixtures/records";
import { RACES } from "../fixtures/races";
import { brierWinner, podiumCall, scoreRound } from "./scoring";

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
  /** Position-exact podium rate across played rounds; null before any round. */
  exactHitRate: number | null;
  /** Mean winner-distribution Brier; null for the player (no distribution). */
  meanBrier: number | null;
}

/** One competitor's call for a race: the player's lock, or a model's podium call. */
export function callForCompetitor(
  record: PredictionRecord,
  _raceId: string,
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

interface MutableEntry {
  points: number;
  rounds: number;
  exact: number;
  brierSum: number;
}

/**
 * Season standings over the played rounds. Pure over the pit-wall record —
 * identical input, identical table.
 */
export function seasonStandings(record: PitWallRecord): StandingsEntry[] {
  const played: RaceSummary[] = RACES.filter((race) => record.calls[race.raceId]);
  const mutable = new Map<CompetitorId, MutableEntry>(
    COMPETITORS.map((id) => [id, { points: 0, rounds: 0, exact: 0, brierSum: 0 }]),
  );

  for (const race of played) {
    const sheet: CallSheet | undefined = CALL_SHEETS[race.raceId];
    const predictionRecord = RECORDS_BY_RACE_ID[race.raceId];
    if (!sheet || !predictionRecord) continue; // Fixture data must ship as a pair.
    const flag = predictionRecord.ensemble.consensus.flag;
    const winnerId = sheet.finishingOrder[0];
    const playerCall = record.calls[race.raceId];

    for (const competitor of COMPETITORS) {
      const entry = mutable.get(competitor);
      if (!entry) continue;
      const call = callForCompetitor(predictionRecord, race.raceId, competitor, playerCall);
      if (!call) continue;
      const score = scoreRound(call, sheet.finishingOrder, flag);
      entry.points += score.total;
      entry.rounds += 1;
      if (score.positionExactCount === 3) entry.exact += 1;
      if (competitor !== "you") {
        const distribution: ProbabilityMap =
          competitor === "ensemble"
            ? predictionRecord.ensemble.winner
            : predictionRecord.models[competitor as ModelId].winner;
        entry.brierSum += brierWinner(distribution, winnerId);
      }
    }
  }

  return COMPETITORS.map((competitorId) => {
    const entry = mutable.get(competitorId);
    const rounds = entry?.rounds ?? 0;
    return {
      competitorId,
      points: entry?.points ?? 0,
      roundsPlayed: rounds,
      exactHitRate: rounds > 0 ? (entry?.exact ?? 0) / rounds : null,
      meanBrier:
        competitorId !== "you" && rounds > 0 ? (entry?.brierSum ?? 0) / rounds : null,
    };
  }).sort((a, b) => b.points - a.points || (b.exactHitRate ?? 0) - (a.exactHitRate ?? 0));
}

export interface NearMissFeedback {
  /** The pick that finished P4. */
  driverId: string;
  /** The slot the player picked them in (1–3). */
  pickedSlot: number;
  /** "The ensemble had him P3 — it knew." when the ensemble's podium call included them. */
  ensembleKnew: boolean;
}

/**
 * The near-miss line's raw material: a player pick that finished P4, and
 * whether the ensemble's podium call had them. Pure lookup for the reveal
 * and the Gauntlet's feedback line.
 */
export function nearMiss(raceId: string, call: RoundCall): NearMissFeedback | null {
  const sheet = CALL_SHEETS[raceId];
  const record = RECORDS_BY_RACE_ID[raceId];
  if (!sheet || !record) return null;
  const position = new Map(sheet.finishingOrder.map((id, index) => [id, index + 1]));
  const picks: [string, number][] = [
    [call.p1, 1],
    [call.p2, 2],
    [call.p3, 3],
  ];
  const missed = picks.find(([driverId]) => position.get(driverId) === 4);
  if (!missed) return null;
  const [driverId, pickedSlot] = missed;
  const ensembleCall = podiumCall(record.ensemble.podium);
  const ensembleKnew =
    ensembleCall != null &&
    [ensembleCall.p1, ensembleCall.p2, ensembleCall.p3].includes(driverId);
  return { driverId, pickedSlot, ensembleKnew };
}

/** Display names for the Gauntlet table (design doc §4: You vs m1-gbm / m2-logit / m3-form / Ensemble). */
export const COMPETITOR_NAMES: Record<CompetitorId, string> = {
  you: "You",
  "m1-gbm": "m1-gbm",
  "m2-logit": "m2-logit",
  "m3-form": "m3-form",
  ensemble: "Ensemble",
};

/** Played rounds in catalog order with their consensus flag — the per-round chip list. */
export function playedRounds(record: PitWallRecord): { raceId: string; flag: ConsensusFlag }[] {
  return RACES.filter((race) => record.calls[race.raceId]).map((race) => {
    const predictionRecord = RECORDS_BY_RACE_ID[race.raceId];
    return {
      raceId: race.raceId,
      flag: predictionRecord?.ensemble.consensus.flag ?? ("OK" as const),
    };
  });
}

/** The most recent round's near miss, for the Gauntlet's feedback line. */
export function latestNearMiss(record: PitWallRecord): NearMissFeedback | null {
  for (const race of [...RACES].reverse()) {
    const call = record.calls[race.raceId];
    if (!call) continue;
    const miss = nearMiss(race.raceId, call);
    if (miss) return miss;
  }
  return null;
}
