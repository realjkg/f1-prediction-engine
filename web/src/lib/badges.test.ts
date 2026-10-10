import { describe, expect, it } from "vitest";
import { DATA_NERD_THRESHOLD, COLD_READ_PROB_BELOW, badgesForRound } from "./badges";

const BASE = {
  exactPodium: false,
  winnerCalled: false,
  winnerProb: null,
  p2OnPodium: false,
  p3OnPodium: false,
  streakAfterRound: 0,
  playerPoints: 0,
  ensemblePoints: 0,
  evidenceViews: 0,
};

describe("badgesForRound", () => {
  it("awards First Exact Podium on any exact round", () => {
    expect(badgesForRound({ ...BASE, exactPodium: true })).toEqual(["first-exact-podium"]);
  });

  it("awards Three In A Row at the flame threshold", () => {
    expect(badgesForRound({ ...BASE, streakAfterRound: 2 })).toEqual([]);
    expect(badgesForRound({ ...BASE, streakAfterRound: 3 })).toEqual(["three-in-a-row"]);
  });

  it("awards Beat The Ensemble only when strictly ahead", () => {
    expect(badgesForRound({ ...BASE, playerPoints: 20, ensemblePoints: 20 })).toEqual([]);
    expect(badgesForRound({ ...BASE, playerPoints: 21, ensemblePoints: 20 })).toEqual([
      "beat-the-ensemble",
    ]);
  });

  it("awards Cold Read only for a called winner priced below the threshold", () => {
    const atThreshold = { ...BASE, winnerCalled: true, winnerProb: COLD_READ_PROB_BELOW };
    expect(badgesForRound(atThreshold)).toEqual([]);
    expect(badgesForRound({ ...atThreshold, winnerProb: 0.07 })).toEqual(["cold-read"]);
    // No probability context (never the ensemble's price) — no cold read.
    expect(badgesForRound({ ...BASE, winnerCalled: true })).toEqual([]);
  });

  it("awards Data Nerd at the open threshold", () => {
    expect(badgesForRound({ ...BASE, evidenceViews: DATA_NERD_THRESHOLD - 1 })).toEqual([]);
    expect(badgesForRound({ ...BASE, evidenceViews: DATA_NERD_THRESHOLD })).toEqual(["data-nerd"]);
  });

  it("awards Perfect Round for the winner plus both podium picks", () => {
    expect(
      badgesForRound({ ...BASE, winnerCalled: true, p2OnPodium: true, p3OnPodium: true }),
    ).toEqual(["perfect-round"]);
  });

  it("stacks every earned badge in one round", () => {
    const earned = badgesForRound({
      exactPodium: true,
      winnerCalled: true,
      winnerProb: 0.05,
      p2OnPodium: true,
      p3OnPodium: true,
      streakAfterRound: 3,
      playerPoints: 40,
      ensemblePoints: 30,
      evidenceViews: 5,
    });
    expect(earned).toEqual([
      "first-exact-podium",
      "three-in-a-row",
      "beat-the-ensemble",
      "cold-read",
      "data-nerd",
      "perfect-round",
    ]);
  });
});
