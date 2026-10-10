import { describe, expect, it } from "vitest";
import { emptyRecord } from "./pitwall";
import { podiumCall } from "./calls";
import {
  COMPETITORS,
  COMPETITOR_NAMES,
  callForCompetitor,
  playerLeadsEnsemble,
  playedRounds,
  seasonStandings,
  type RoundCompetitorScores,
} from "./standings";
import type {
  ConsensusFlag,
  PitWallRecord,
  PredictionRecord,
  ProbabilityMap,
  RoundCall,
  RoundScoreSummary,
} from "../types";

/** A player summary: all three picks position-exact, winner bonus included. */
function perfectSummary(over: Partial<RoundScoreSummary> = {}): RoundScoreSummary {
  return {
    positionExactCount: 3,
    winnerBonus: true,
    nearMissCount: 0,
    basePoints: 18,
    consensusFlag: "OK",
    coinFlip: false,
    totalPoints: 18,
    ...over,
  };
}

/** A model/ensemble summary — never the player's numbers. */
function competitorSummary(totalPoints: number, flag: ConsensusFlag = "OK"): RoundScoreSummary {
  return {
    positionExactCount: 1,
    winnerBonus: false,
    nearMissCount: 1,
    basePoints: 6,
    consensusFlag: flag,
    coinFlip: flag === "LOW_CONSENSUS",
    totalPoints,
  };
}

function recordWithRound(
  raceKey: string,
  scores: Partial<RoundCompetitorScores> = {},
): PitWallRecord {
  const full: RoundCompetitorScores = {
    you: perfectSummary(),
    "m1-gbm": competitorSummary(12),
    "m2-logit": competitorSummary(9),
    "m3-form": competitorSummary(7),
    ensemble: competitorSummary(11),
  };
  const record = emptyRecord();
  record.roundScores[raceKey] = { ...full, ...scores };
  return record;
}

/** A minimal-but-valid prediction record for callForCompetitor derivations. */
function recordWithDistributions(
  winner: ProbabilityMap,
  podium: ProbabilityMap,
): PredictionRecord {
  const models = {
    "m1-gbm": { winner, podium },
  } as PredictionRecord["models"];
  return {
    schemaVersion: 1,
    recordType: "prediction",
    predictionId: "2024-r1-test",
    race: { season: 2024, round: 1, raceId: "test-gp", name: "Test Grand Prix" },
    generatedAt: "2024-01-01T00:00:00Z",
    dataset: { id: "test", sha256: "0".repeat(64) },
    evidenceBasis: "test",
    models,
    ensemble: {
      raceId: "2024-r1-test",
      winner,
      podium,
      consensus: { podiumSpread: 0.01, flag: "OK" },
      weightsUsed: { "m1-gbm": 1, "m2-logit": 0, "m3-form": 0 },
    },
    advisoryOnly: true,
    dataLimitations: [],
    prevRecordSha256: null,
    recordSha256: "1".repeat(64),
  } as PredictionRecord;
}

describe("seasonStandings", () => {
  it("scores zero rounds for an empty record", () => {
    const standings = seasonStandings(emptyRecord());
    expect(standings).toHaveLength(5);
    for (const entry of standings) {
      expect(entry.points).toBe(0);
      expect(entry.roundsPlayed).toBe(0);
      expect(entry.exactHitRate).toBeNull();
    }
  });

  it("sums stored engine summaries per competitor over played rounds", () => {
    const record = recordWithRound("2024-r1-a");
    // A second round where the ensemble scores 20 — the sum must span rounds.
    record.roundScores["2024-r2-b"] = {
      ...record.roundScores["2024-r1-a"],
      ensemble: competitorSummary(20),
    };
    const standings = seasonStandings(record);
    const ensemble = standings.find((e) => e.competitorId === "ensemble");
    expect(ensemble?.points).toBe(11 + 20);
    expect(ensemble?.roundsPlayed).toBe(2);
    expect(ensemble?.exactHitRate).toBe(0); // never all-three-exact in these fixtures
  });

  it("ranks a perfect player round at the top", () => {
    const standings = seasonStandings(recordWithRound("2024-r1-a"));
    const you = standings.find((e) => e.competitorId === "you");
    expect(you?.points).toBe(18);
    expect(you?.roundsPlayed).toBe(1);
    expect(you?.exactHitRate).toBe(1);
    expect(standings[0].competitorId).toBe("you");
  });

  it("skips rounds where a competitor has no stored summary", () => {
    const record = recordWithRound("2024-r1-a", { "m3-form": undefined });
    const form = seasonStandings(record).find((e) => e.competitorId === "m3-form");
    expect(form?.roundsPlayed).toBe(0);
    expect(form?.points).toBe(0);
  });
});

describe("playedRounds", () => {
  it("lists played rounds with the engine-served consensus flag", () => {
    const played = playedRounds(
      recordWithRound("2024-r1-a", {
        you: perfectSummary({ consensusFlag: "LOW_CONSENSUS", coinFlip: true, totalPoints: 36 }),
      }),
    );
    expect(played).toEqual([{ raceKey: "2024-r1-a", flag: "LOW_CONSENSUS" }]);
  });

  it("reports a null flag when no player summary exists", () => {
    const played = playedRounds(recordWithRound("2024-r1-a", { you: undefined }));
    expect(played).toEqual([{ raceKey: "2024-r1-a", flag: null }]);
  });
});

describe("playerLeadsEnsemble", () => {
  it("is false before any round", () => {
    expect(playerLeadsEnsemble(emptyRecord())).toBe(false);
  });

  it("is true when the player's total beats the ensemble's", () => {
    const record = recordWithRound("2024-r1-a", { ensemble: competitorSummary(2) });
    expect(playerLeadsEnsemble(record)).toBe(true);
  });
});

describe("callForCompetitor", () => {
  const winner: ProbabilityMap = { "1-max": 0.5, "44-ham": 0.3, "4-nor": 0.2 };
  const podium: ProbabilityMap = { "1-max": 0.8, "44-ham": 0.7, "4-nor": 0.6 };
  const record = recordWithDistributions(winner, podium);
  const playerCall: RoundCall = { p1: "44-ham", p2: "1-max", p3: "4-nor" };

  it("returns the player's own lock unchanged", () => {
    expect(callForCompetitor(record, "you", playerCall)).toEqual(playerCall);
  });

  it("derives model and ensemble calls from the podium distribution", () => {
    expect(callForCompetitor(record, "m1-gbm", null)).toEqual({ p1: "1-max", p2: "44-ham", p3: "4-nor" });
    expect(callForCompetitor(record, "ensemble", null)).toEqual({ p1: "1-max", p2: "44-ham", p3: "4-nor" });
  });

  it("returns null when a distribution cannot name three drivers", () => {
    const thin = recordWithDistributions({ "1-max": 1 }, { "1-max": 1 });
    expect(callForCompetitor(thin, "m1-gbm", null)).toBeNull();
  });
});

describe("podiumCall (display derivation)", () => {
  it("takes the top three with descending-probability, id tie-break", () => {
    const call = podiumCall({ "4-nor": 0.3, "1-max": 0.3, "44-ham": 0.9, "5-alb": 0.1 });
    expect(call).toEqual({ p1: "44-ham", p2: "1-max", p3: "4-nor" });
  });
});

describe("COMPETITOR_NAMES", () => {
  it("labels every competitor for the Gauntlet table", () => {
    expect(COMPETITORS.map((id) => COMPETITOR_NAMES[id])).toEqual([
      "You",
      "m1-gbm",
      "m2-logit",
      "m3-form",
      "Ensemble",
    ]);
  });
});
