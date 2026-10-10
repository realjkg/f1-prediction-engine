import { beforeEach, describe, expect, it } from "vitest";
import {
  applyLockedRound,
  browserStorage,
  clearRecord,
  emptyRecord,
  hydrate,
  loadRecord,
  saveRecord,
} from "./pitwall";
import type { CallScore, PitWallRecord, PredictionRecord, RoundScoreSummary } from "../types";

/** A stored engine summary for one competitor. */
function summary(totalPoints: number, flag: RoundScoreSummary["consensusFlag"] = "OK"): RoundScoreSummary {
  return {
    positionExactCount: 1,
    winnerBonus: false,
    nearMissCount: 0,
    basePoints: 6,
    consensusFlag: flag,
    coinFlip: flag === "LOW_CONSENSUS",
    totalPoints,
  };
}

/** A fully engine-scored round — all five competitors, as locks persist them. */
function scoredRound(playerTotal = 18): PitWallRecord["roundScores"][string] {
  const you: RoundScoreSummary =
    playerTotal === 18
      ? {
          positionExactCount: 3,
          winnerBonus: true,
          nearMissCount: 0,
          basePoints: 18,
          consensusFlag: "OK",
          coinFlip: false,
          totalPoints: 18,
        }
      : summary(playerTotal);
  return {
    you,
    "m1-gbm": summary(12),
    "m2-logit": summary(9),
    "m3-form": summary(7),
    ensemble: summary(11),
  };
}

describe("hydrate", () => {
  it("returns an empty record for non-objects", () => {
    expect(hydrate(null)).toEqual(emptyRecord());
    expect(hydrate("garbage")).toEqual(emptyRecord());
  });

  it("keeps calls that have engine scores and drops orphaned ones", () => {
    // A call without the engine's stored score cannot be displayed honestly.
    const record = hydrate({
      calls: {
        "2024-01": { p1: "a", p2: "b", p3: "c" },
        "2024-02": { p1: "a", p2: "b", p3: "c" },
      },
      roundScores: { "2024-01": scoredRound() },
    });
    expect(Object.keys(record.calls)).toEqual(["2024-01"]);
    expect(Object.keys(record.roundScores)).toEqual(["2024-01"]);
  });

  it("drops a round atomically when one competitor's score block is malformed", () => {
    const scores = scoredRound();
    delete (scores as Record<string, unknown>)["m2-logit"];
    const record = hydrate({
      calls: { "2024-01": { p1: "a", p2: "b", p3: "c" } },
      roundScores: { "2024-01": scores },
    });
    expect(record.calls).toEqual({});
    expect(record.roundScores).toEqual({});
  });

  it("preserves the dataset digest binding on a stored call", () => {
    const record = hydrate({
      calls: { "2024-01": { p1: "a", p2: "b", p3: "c", datasetDigest: "deadbeef" } },
      roundScores: { "2024-01": scoredRound() },
    });
    expect(record.calls["2024-01"]?.datasetDigest).toBe("deadbeef");
  });

  it("defaults missing counters and coerces wrong types", () => {
    const record = hydrate({ streak: "three", evidenceViews: "many" });
    expect(record.streak).toBe(0);
    expect(record.evidenceViews).toBe(0);
    expect(record.freshEyes).toBe(false);
  });
});

describe("applyLockedRound", () => {
  const call = { p1: "1-max", p2: "44-ham", p3: "4-nor" };

  /** Minimal prediction record — badges only read the ensemble's win distribution. */
  function predictionRecord(winnerProb: number): PredictionRecord {
    return {
      schemaVersion: 1,
      recordType: "prediction",
      predictionId: "2024-01-test",
      race: { season: 2024, round: 1, raceId: "test-gp", name: "Test Grand Prix" },
      generatedAt: "2024-01-01T00:00:00Z",
      dataset: { id: "test", sha256: "0".repeat(64) },
      evidenceBasis: "test",
      models: {},
      ensemble: {
        raceId: "2024-01-test",
        winner: { "1-max": winnerProb },
        podium: {},
        consensus: { podiumSpread: 0.01, flag: "OK" },
        weightsUsed: { "m1-gbm": 1, "m2-logit": 0, "m3-form": 0 },
      },
      advisoryOnly: true,
      dataLimitations: [],
      prevRecordSha256: null,
      recordSha256: "1".repeat(64),
      // Only ensemble.winner is read by badge evaluation — models stay empty.
    } as unknown as PredictionRecord;
  }

  /** Minimal player CallScore — only the streak block is read. */
  function playerScore(after: number): CallScore {
    return {
      raceId: "2024-01-test",
      round: {
        picks: [
          { slot: "p1", driverId: "1-max", actualPosition: 1, outcome: "EXACT", points: 5 },
          { slot: "p2", driverId: "44-ham", actualPosition: 2, outcome: "EXACT", points: 5 },
          { slot: "p3", driverId: "4-nor", actualPosition: 3, outcome: "EXACT", points: 5 },
        ],
        basePoints: 18,
        consensusFlag: "OK",
        coinFlip: false,
        totalPoints: 18,
      },
      streak: { before: after - 1, after, delta: 1, flame: after >= 3 },
    } as CallScore;
  }

  it("folds the engine-scored round into the record with streak and badges", () => {
    const next = applyLockedRound(
      emptyRecord(),
      "2024-01",
      call,
      scoredRound(18),
      playerScore(1),
      predictionRecord(0.38),
    );
    expect(next.calls["2024-01"]).toEqual(call);
    expect(next.roundScores["2024-01"]?.you.totalPoints).toBe(18);
    expect(next.streak).toBe(1);
    expect(next.bestStreak).toBe(1);
    expect(next.badges).toContain("first-exact-podium");
    expect(next.badges).toContain("perfect-round");
  });

  it("keeps the maximum best streak across rounds", () => {
    const first = applyLockedRound(
      emptyRecord(),
      "2024-01",
      call,
      scoredRound(),
      playerScore(3),
      predictionRecord(0.38),
    );
    expect(first.bestStreak).toBe(3);
  });
});

describe("loadRecord / saveRecord / clearRecord", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("round-trips a record through localStorage", () => {
    const storage = browserStorage();
    const record: PitWallRecord = {
      ...emptyRecord(),
      profileName: "KG",
      calls: { "2024-01": { p1: "a", p2: "b", p3: "c", datasetDigest: "deadbeef" } },
      roundScores: { "2024-01": scoredRound() },
      streak: 1,
      bestStreak: 2,
      evidenceViews: 2,
      freshEyes: true,
    };
    saveRecord(storage, record);
    expect(loadRecord(storage)).toEqual(record);
  });

  it("starts clean when nothing is stored", () => {
    expect(loadRecord(browserStorage())).toEqual(emptyRecord());
  });

  it("starts clean on corrupt JSON instead of crashing", () => {
    window.localStorage.setItem("pitwall.record.v1", "{not json");
    expect(loadRecord(browserStorage())).toEqual(emptyRecord());
  });

  it("clears the stored record", () => {
    const storage = browserStorage();
    saveRecord(storage, { ...emptyRecord(), profileName: "KG" });
    clearRecord(storage);
    expect(loadRecord(storage)).toEqual(emptyRecord());
  });
});
