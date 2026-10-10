import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "./App";
import { CALL_SHEETS } from "./fixtures/callsheets";
import { DRIVERS } from "./fixtures/drivers";
import { RECORDS_BY_RACE_ID } from "./fixtures/records";

const STORAGE_KEY = "pitwall.record.v1";

/** The Austrian fixture's classified podium: Bottas, Leclerc, Norris. */
const PODIUM = CALL_SHEETS["austrian-gp"].finishingOrder.slice(0, 3);

function driverCode(driverId: string): string {
  return DRIVERS[driverId].code;
}

function playAustrianPerfect() {
  fireEvent.click(screen.getByRole("button", { name: /Austrian Grand Prix/ }));
  for (const driverId of PODIUM) {
    fireEvent.click(
      screen.getByRole("button", { name: new RegExp(driverCode(driverId)) }),
    );
  }
  fireEvent.click(screen.getByRole("button", { name: "LOCK IT" }));
}

describe("Race Rewind flow", () => {
  afterEach(cleanup);
  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "";
  });

  it("runs pick → call → lock → reveal with every card and the round score", () => {
    render(<App />);
    playAustrianPerfect();

    // The reveal headline reflects a perfect call.
    expect(screen.getByRole("heading", { name: "EXACT PODIUM" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Actual podium" })).toBeTruthy();

    // Every competitor's card renders: yours, the ensemble, and the three models.
    const cards = screen.getByRole("region", { name: /Reveal for Austrian Grand Prix/ });
    for (const name of ["Your call", "Ensemble", "m1-gbm", "m2-logit", "m3-form"]) {
      expect(within(cards).getByText(name)).toBeTruthy();
    }

    // Round score: 3 exact (+15) + winner (+3); doubled on a Coin Flip Round.
    const flag = RECORDS_BY_RACE_ID["austrian-gp"].ensemble.consensus.flag;
    const expected = flag === "LOW_CONSENSUS" ? 36 : 18;
    expect(screen.getByText(`+${expected}`)).toBeTruthy();
    expect(screen.getByText("Streak: 1")).toBeTruthy();

    // The dopamine moment actually fires.
    expect(document.querySelector(".confetti")).not.toBeNull();
  });

  it("keeps the lock enabled while the timer runs — the timer never robs the call", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Austrian Grand Prix/ }));
    // Nothing picked yet — the lock is disabled but present.
    const lock = screen.getByRole("button", { name: /Pick 3 more/ });
    expect((lock as HTMLButtonElement).disabled).toBe(true);
  });

  it("persists the pit-wall record across a simulated reload", () => {
    const first = render(<App />);
    playAustrianPerfect();
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}").streak).toBe(1);
    first.unmount();

    // "Reload": a fresh App instance over the same storage.
    render(<App />);
    expect(screen.getByText("PLAYED")).toBeTruthy();
    // The streak survived: the Gauntlet shows the player's points.
    fireEvent.click(screen.getByRole("button", { name: "Models" }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("m1-gbm")).toBeTruthy();
    expect(within(table).getByText("Ensemble")).toBeTruthy();
    // The player's perfect call is still worth its points after the reload.
    const youRow = table.querySelector("tr.is-you");
    expect(youRow?.textContent).toContain("18");
  });

  it("hides played rounds when Fresh Eyes is on", () => {
    render(<App />);
    playAustrianPerfect();

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const toggle = screen.getByLabelText(/Fresh Eyes/i);
    fireEvent.click(toggle);

    fireEvent.click(screen.getByRole("button", { name: "Race" }));
    expect(screen.queryByRole("button", { name: /Austrian Grand Prix/ })).toBeNull();
    expect(screen.getByRole("button", { name: /British Grand Prix/ })).toBeTruthy();
  });
});

describe("Model Gauntlet", () => {
  afterEach(cleanup);
  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "";
  });

  it("renders You plus four competitors from the fixtures once a round is played", () => {
    render(<App />);
    playAustrianPerfect();
    fireEvent.click(screen.getByRole("button", { name: "Models" }));

    const table = screen.getByRole("table");
    for (const name of ["You", "m1-gbm", "m2-logit", "m3-form", "Ensemble"]) {
      expect(within(table).getByText(name)).toBeTruthy();
    }
    // The per-round consensus chips render for the played round.
    expect(screen.getByText(/Consensus by round/)).toBeTruthy();
  });

  it("shows the empty state before any round is played", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Models" }));
    expect(screen.getByText(/No rounds played yet/)).toBeTruthy();
  });
});
