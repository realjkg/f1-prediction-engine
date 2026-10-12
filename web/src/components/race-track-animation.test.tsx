import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { RaceTrackAnimation } from "./RaceTrackAnimation";

afterEach(() => cleanup());

describe("Race Rewind car animation", () => {
  it("labels its cars as decorative and shows real game progress", () => {
    render(<RaceTrackAnimation playedRounds={4} streak={2} badges={3} />);
    expect(screen.getByText(/not real positions/i)).toBeTruthy();
    const progress = screen.getByLabelText("Your Replay progress");
    expect(within(progress).getByText("4")).toBeTruthy();
    expect(within(progress).getByText("2")).toBeTruthy();
    expect(within(progress).getByText("3")).toBeTruthy();
    expect(screen.getByRole("img", { name: /fictional open-wheel cars/i })).toBeTruthy();
  });

  it("pauses and resumes, and changes only visual speed", () => {
    const { container } = render(<RaceTrackAnimation playedRounds={0} streak={0} badges={0} />);
    const stage = container.querySelector(".race-motion__stage");
    expect(stage?.getAttribute("data-motion")).toBe("playing");
    fireEvent.click(screen.getByRole("button", { name: "Pause cars" }));
    expect(stage?.getAttribute("data-motion")).toBe("paused");
    fireEvent.click(screen.getByRole("button", { name: "Resume cars" }));
    expect(stage?.getAttribute("data-motion")).toBe("playing");
    fireEvent.click(screen.getByRole("button", { name: /Change visual speed, currently 1 times/ }));
    expect(stage?.getAttribute("data-speed")).toBe("2");
  });
});
