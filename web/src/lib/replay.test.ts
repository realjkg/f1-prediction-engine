import { describe, expect, it } from "vitest";
import { REPLAY_RUNS, replayStrip, replaySummary } from "./replay";

const total = (strip: ReturnType<typeof replayStrip>) =>
  strip.groups.reduce((sum, group) => sum + group.dots, 0) + strip.otherDots;

describe("replayStrip", () => {
  it("always allocates exactly the number of runs", () => {
    const distributions: Record<string, number>[] = [
      { a: 0.31, b: 0.22, c: 0.17, d: 0.1, e: 0.2 },
      { a: 1 / 3, b: 1 / 3, c: 1 / 3 },
      { a: 0.5, b: 0.5 },
      { a: 0.04, b: 0.04, c: 0.04, d: 0.88 },
    ];
    for (const distribution of distributions) {
      expect(total(replayStrip(distribution))).toBe(REPLAY_RUNS);
    }
  });

  it("orders drivers by likelihood and folds unnamed drivers into others", () => {
    const strip = replayStrip({ low: 0.02, top: 0.6, mid: 0.3, tiny: 0.08 }, 20, 2);
    expect(strip.groups.map((group) => group.driverId)).toEqual(["top", "mid"]);
    expect(strip.groups.map((group) => group.dots)).toEqual([12, 6]);
    expect(strip.otherDots).toBe(2);
  });

  it("normalizes a distribution that does not sum to one", () => {
    const strip = replayStrip({ a: 0.3, b: 0.3 });
    expect(strip.groups.map((group) => group.dots)).toEqual([10, 10]);
    expect(strip.otherDots).toBe(0);
  });

  it("handles an empty or zero distribution without throwing", () => {
    expect(replayStrip({})).toEqual({ groups: [], otherDots: REPLAY_RUNS, runs: REPLAY_RUNS });
    expect(replayStrip({ a: 0 }).groups).toEqual([]);
  });

  it("writes a spoken summary", () => {
    const strip = replayStrip({ ver: 0.3, nor: 0.2, ham: 0.5 }, 20, 2);
    expect(replaySummary(strip, (id) => id.toUpperCase())).toBe(
      "If this race ran 20 times: HAM wins about 10, VER about 6, all others 4.",
    );
  });
});
