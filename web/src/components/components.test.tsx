import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ConsensusChip } from "./ConsensusChip";
import { ProbabilityBars } from "./ProbabilityBars";
import { timerAnnouncement } from "./CallSheetView";
import { revealHeadline } from "./RevealView";

afterEach(cleanup);

describe("ConsensusChip", () => {
  it("uses plain language and keeps the engine flag on a data attribute", () => {
    render(<ConsensusChip flag="LOW_CONSENSUS" coinFlip />);
    const chip = screen.getByText(/Models disagree/);
    expect(chip.getAttribute("data-flag")).toBe("LOW_CONSENSUS");
    expect(chip.textContent).toContain("Coin flip, points double");
    expect(chip.textContent).not.toContain("LOW_CONSENSUS");
  });

  it("labels agreement without the coin-flip suffix", () => {
    render(<ConsensusChip flag="OK" coinFlip />);
    expect(screen.getByText("Models agree")).toBeTruthy();
  });
});

describe("ProbabilityBars", () => {
  it("exposes every row to assistive tech as a labeled list with text values", () => {
    render(
      <ProbabilityBars
        distribution={{ alpha: 0.6, beta: 0.003, gamma: 0.2 }}
        count={3}
        label="Winner probabilities"
      />,
    );
    const list = screen.getByRole("list", { name: "Winner probabilities" });
    expect(list.querySelectorAll("li")).toHaveLength(3);
    expect(screen.getByText("60%")).toBeTruthy();
    // A real but tiny chance is never printed as 0%.
    expect(screen.getByText("<1%")).toBeTruthy();
  });
});

describe("timerAnnouncement", () => {
  it("speaks only at the 10-second warning and at zero", () => {
    expect(timerAnnouncement(30)).toBe("");
    expect(timerAnnouncement(11)).toBe("");
    expect(timerAnnouncement(10)).toMatch(/10 seconds left/);
    expect(timerAnnouncement(5)).toBe("");
    expect(timerAnnouncement(0)).toMatch(/Time is up/);
  });
});

describe("revealHeadline", () => {
  const miss = (slot: "p1" | "p2" | "p3") => ({ slot, driverId: "x", actualPosition: 9, outcome: "MISS" as const, points: 0 });
  const zeroRound = {
    picks: [miss("p1"), miss("p2"), miss("p3")],
    basePoints: 0,
    consensusFlag: null,
    coinFlip: false,
    totalPoints: 0,
  };

  it("only claims the machine saw it coming when its podium held a real finisher", () => {
    expect(revealHeadline(zeroRound, true)).toBe("THE MACHINE SAW IT COMING");
    expect(revealHeadline(zeroRound, false)).toBe("NOBODY SAW THAT COMING");
  });

  it("keeps the scoring headlines unchanged", () => {
    expect(revealHeadline({ ...zeroRound, totalPoints: 2 }, false)).toBe("ON THE BOARD");
    const winner = { ...zeroRound, totalPoints: 8, picks: [{ ...miss("p1"), outcome: "EXACT" as const }, miss("p2"), miss("p3")] };
    expect(revealHeadline(winner, false)).toBe("WINNER CALLED");
  });
});
