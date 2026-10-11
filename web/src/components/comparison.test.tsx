import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { PredictionRecord } from "../types";
import { ModelComparison } from "./ModelComparison";
import { ReplayDots } from "./ReplayDots";

afterEach(cleanup);

const record = {
  race: { name: "Test Grand Prix" },
  ensemble: { winner: { alpha: 0.5, beta: 0.3, gamma: 0.15, delta: 0.05 } },
  models: {
    "m1-gbm": { winner: { alpha: 0.7, beta: 0.2, gamma: 0.1 } },
    "m2-logit": { winner: { alpha: 0.4, beta: 0.4, gamma: 0.2 } },
    "m3-form": { winner: { alpha: 0.4, beta: 0.3, gamma: 0.15, delta: 0.003 } },
  },
} as unknown as PredictionRecord;

describe("ModelComparison", () => {
  it("lays out drivers as rows and the models plus ensemble as columns", () => {
    render(<ModelComparison record={record} count={3} />);
    const table = screen.getByRole("table", { name: "Test Grand Prix win probability by model" });
    expect(within(table).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Driver",
      "m1-gbm",
      "m2-logit",
      "m3-form",
      "Ensemble",
    ]);
    // Header row plus three driver rows, ranked by the ensemble's win probability.
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getByText("70%")).toBeTruthy();
  });

  it("never prints a real but tiny chance as 0%", () => {
    render(<ModelComparison record={record} count={4} />);
    expect(screen.getByText("<1%")).toBeTruthy();
  });
});

describe("ReplayDots", () => {
  it("announces a spoken summary and marks the actual winner", () => {
    const { container } = render(<ReplayDots distribution={record.ensemble.winner} actualWinnerId="beta" />);
    const figure = screen.getByRole("figure");
    expect(figure.getAttribute("aria-label")).toMatch(/If this race ran 20 times: .* wins about 10/);
    expect(container.querySelectorAll(".replay-dot")).toHaveLength(20);
    expect(container.querySelector(".is-actual")).toBeTruthy();
  });

  it("renders nothing when there is no distribution", () => {
    const { container } = render(<ReplayDots distribution={{}} />);
    expect(container.querySelector(".replay")).toBeNull();
  });
});
