import { describe, expect, it } from "vitest";
import {
  formatHitFraction,
  formatPercent,
  hitCount,
  randomWinnerRate,
  uniformBrier,
} from "./baseline";

describe("baseline helpers", () => {
  it("computes the chance of a random winner pick", () => {
    expect(randomWinnerRate(20)).toBeCloseTo(0.05);
  });

  it("computes the uniform multi-class Brier score", () => {
    expect(uniformBrier(20)).toBeCloseTo(0.95);
    expect(uniformBrier(2)).toBeCloseTo(0.5);
  });

  it("turns a rate into whole rounds", () => {
    expect(hitCount(0.25, 24)).toBe(6);
    expect(formatHitFraction(0.25, 24)).toBe("6 of 24 (25%)");
  });

  it("never shows a nonzero chance as 0%", () => {
    expect(formatPercent(0.004)).toBe("<1%");
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(0.314)).toBe("31%");
  });
});
