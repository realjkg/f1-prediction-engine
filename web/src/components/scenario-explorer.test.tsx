import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { InRaceScenario } from "../types";
import { ScenarioExplorer } from "./ScenarioExplorer";

afterEach(() => cleanup());
const scenario = {
  checkpointLap: 25,
  trials: 500,
  drivers: [
    { driverNumber: 16, currentPosition: 2, currentGapSeconds: 1.1, conditionalWinFrequency: 0.31, conditionalTopFourFrequency: 0.72, estimatedGreenLapSeconds: 95 },
    { driverNumber: 55, currentPosition: 1, currentGapSeconds: 0, conditionalWinFrequency: 0.62, conditionalTopFourFrequency: 0.85, estimatedGreenLapSeconds: 94 },
  ],
} as InRaceScenario;

describe("verified scenario explorer", () => {
  it("uses stored driver frequencies and changes only the focused driver", () => {
    render(<ScenarioExplorer scenario={scenario} />);
    expect(screen.getByText("62.0%")).toBeTruthy();
    expect(screen.getByText("85.0%")).toBeTruthy();
    expect(screen.getByText(/never triggers new inference/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /#16/ }));
    expect(screen.getByText("31.0%")).toBeTruthy();
    expect(screen.getByText("72.0%")).toBeTruthy();
    expect(screen.getByText("Recorded position P2")).toBeTruthy();
  });
});
