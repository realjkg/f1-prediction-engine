import { describe, expect, it } from "vitest";
import {
  brierWinner,
  COIN_FLIP_MULTIPLIER,
  podiumCall,
  scoreRound,
  streakExtends,
  WINNER_BONUS,
} from "./scoring";

/** Positions 1–8: a is the winner, d finishes P4 (the near-miss slot). */
const ORDER = ["a", "b", "c", "d", "e", "f", "g", "h"];

describe("scoreRound", () => {
  it("scores a position-exact podium with the winner bonus", () => {
    const score = scoreRound({ p1: "a", p2: "b", p3: "c" }, ORDER, "OK");
    expect(score.positionExactCount).toBe(3);
    expect(score.winnerBonus).toBe(true);
    expect(score.nearMissCount).toBe(0);
    expect(score.basePoints).toBe(18);
    expect(score.multiplier).toBe(1);
    expect(score.total).toBe(18);
    expect(score.perfectRound).toBe(true);
  });

  it("doubles the total on a Coin Flip Round (LOW_CONSENSUS)", () => {
    const score = scoreRound({ p1: "a", p2: "b", p3: "c" }, ORDER, "LOW_CONSENSUS");
    expect(score.multiplier).toBe(COIN_FLIP_MULTIPLIER);
    expect(score.total).toBe(18 * COIN_FLIP_MULTIPLIER);
  });

  it("scores the P4 near miss (+1) alongside exact picks", () => {
    // a wins (+5+3), b P2 exact (+5), d — picked P3 — finished P4 (+1).
    const score = scoreRound({ p1: "a", p2: "b", p3: "d" }, ORDER, "OK");
    expect(score.positionExactCount).toBe(2);
    expect(score.nearMissCount).toBe(1);
    expect(score.basePoints).toBe(5 + WINNER_BONUS + 5 + 1);
    expect(score.total).toBe(14);
    expect(score.perfectRound).toBe(false);
  });

  it("ignores picks outside the top four", () => {
    const score = scoreRound({ p1: "a", p2: "e", p3: "f" }, ORDER, "OK");
    expect(score.positionExactCount).toBe(1);
    expect(score.nearMissCount).toBe(0);
    expect(score.basePoints).toBe(8);
  });

  it("pays exact-position points only when the pick matches its own slot", () => {
    // c P1 (finished P3), b P2 (exact), a P3 (finished P1) — only b is slot-exact.
    const score = scoreRound({ p1: "c", p2: "b", p3: "a" }, ORDER, "OK");
    expect(score.positionExactCount).toBe(1);
    expect(score.winnerBonus).toBe(false);
    expect(score.basePoints).toBe(5);
    expect(score.perfectRound).toBe(false);
  });

  it("scores zero for a call with nothing right", () => {
    const score = scoreRound({ p1: "x", p2: "b", p3: "c" }, ORDER, "OK");
    expect(score.positionExactCount).toBe(2);
    // Winner was a; the player's P1 pick is not even in the field.
    expect(score.basePoints).toBe(10);
  });
});

describe("streakExtends", () => {
  it("extends on any position-exact hit", () => {
    expect(streakExtends({ ...scoreRound({ p1: "a", p2: "e", p3: "f" }, ORDER, "OK") })).toBe(true);
  });

  it("resets when nothing was position-exact", () => {
    const score = scoreRound({ p1: "d", p2: "e", p3: "f" }, ORDER, "OK");
    expect(score.positionExactCount).toBe(0);
    expect(streakExtends(score)).toBe(false);
  });
});

describe("podiumCall", () => {
  it("takes the top three by probability, descending", () => {
    expect(podiumCall({ a: 0.5, b: 0.3, c: 0.2, d: 0.1 })).toEqual({
      p1: "a",
      p2: "b",
      p3: "c",
    });
  });

  it("tie-breaks equal probabilities by driver id", () => {
    expect(podiumCall({ b: 0.4, a: 0.4, c: 0.2 })).toEqual({
      p1: "a",
      p2: "b",
      p3: "c",
    });
  });

  it("returns null when the distribution cannot fill a podium", () => {
    expect(podiumCall({ a: 0.9, b: 0.1 })).toBeNull();
  });
});

describe("brierWinner", () => {
  it("matches the hand-computed multiclass score", () => {
    // (0.7-1)^2 + (0.3-0)^2 = 0.09 + 0.09
    expect(brierWinner({ a: 0.7, b: 0.3 }, "a")).toBeCloseTo(0.18, 10);
  });

  it("penalizes confident wrong calls", () => {
    // (0.7-0)^2 + (0.3-1)^2 = 0.49 + 0.49
    expect(brierWinner({ a: 0.7, b: 0.3 }, "b")).toBeCloseTo(0.98, 10);
  });
});
