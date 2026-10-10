import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "./App";
import { installMockEngine, type MockEngine } from "./test/mockEngine";

const STORAGE_KEY = "pitwall.record.v1";

/**
 * The perfect Bahrain call — the actual podium, typed into the sheet. The
 * mock engine scores it (mirroring the engine's published table); the UI
 * under test only ever renders those served numbers.
 */
const PODIUM_CODES = ["VER", "LEC", "PER"];

async function openBahrain() {
  fireEvent.click(await screen.findByRole("button", { name: /Bahrain Grand Prix/ }));
  await screen.findByRole("region", { name: "Call sheet for Bahrain Grand Prix" });
}

async function playBahrainPerfect() {
  await openBahrain();
  for (const code of PODIUM_CODES) {
    fireEvent.click(screen.getByRole("button", { name: new RegExp(code) }));
  }
  fireEvent.click(screen.getByRole("button", { name: "LOCK IT" }));
  // The lock runs five engine score requests; the reveal lands when done.
  await screen.findByRole("region", { name: /Reveal for Bahrain Grand Prix/ });
}

describe("Race Rewind flow (engine-scored)", () => {
  let engine: MockEngine;

  afterEach(() => {
    cleanup();
    engine.restore();
  });

  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "";
    engine = installMockEngine();
  });

  it("runs pick → lock → reveal with every card and the ENGINE-computed round score", async () => {
    render(<App />);
    await playBahrainPerfect();

    // The reveal headline reflects the perfect call.
    expect(screen.getByRole("heading", { name: "EXACT PODIUM" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Actual podium" })).toBeTruthy();

    // Every competitor's card renders: yours, the ensemble, and the three models.
    const reveal = screen.getByRole("region", { name: /Reveal for Bahrain Grand Prix/ });
    for (const name of ["Your call", "Ensemble", "m1-gbm", "m2-logit", "m3-form"]) {
      expect(within(reveal).getByText(name)).toBeTruthy();
    }

    // Round score: 3 exact (+15) + winner (+3) — the mock engine's number,
    // rendered verbatim; the client computed nothing.
    expect(within(reveal).getByText("+18")).toBeTruthy();
    expect(within(reveal).getByText("Streak: 1")).toBeTruthy();

    // The dopamine moment actually fires.
    expect(reveal.querySelector(".confetti")).not.toBeNull();

    // The lock really went through the engine: five score calls, player last-streak 0.
    const scoreCalls = engine.requests.filter((url) => url.includes("/score?"));
    expect(scoreCalls).toHaveLength(5);
    expect(scoreCalls[0]).toContain("call=max_verstappen,leclerc,perez");
  });

  it("keeps the lock disabled while the call is incomplete — and shows the timer", async () => {
    render(<App />);
    await openBahrain();
    // Nothing picked yet — the lock is disabled but present.
    const lock = screen.getByRole("button", { name: /Pick 3 more/ });
    expect((lock as HTMLButtonElement).disabled).toBe(true);
    expect(document.querySelector(".call-sheet-timer")).not.toBeNull();
  });

  it("persists the pit-wall record across a simulated reload", async () => {
    const first = render(<App />);
    await playBahrainPerfect();
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    expect(stored.streak).toBe(1);
    expect(Object.keys(stored.roundScores)).toEqual(["2024-r1-bahrain-gp"]);
    first.unmount();

    // "Reload": a fresh App instance over the same storage and mock engine.
    render(<App />);
    await screen.findByRole("heading", { name: "Pick a round" });
    expect(screen.getByText("PLAYED")).toBeTruthy();

    // The Gauntlet shows the player's points from the stored engine summaries.
    fireEvent.click(screen.getByRole("button", { name: "Models" }));
    const table = await screen.findByRole("table");
    expect(within(table).getByText("m1-gbm")).toBeTruthy();
    expect(within(table).getByText("Ensemble")).toBeTruthy();
    const youRow = table.querySelector("tr.is-you");
    expect(youRow?.textContent).toContain("18");
  });

  it("hides played rounds when Fresh Eyes is on", async () => {
    render(<App />);
    await playBahrainPerfect();

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const toggle = await screen.findByLabelText(/Fresh Eyes/i);
    fireEvent.click(toggle);

    fireEvent.click(screen.getByRole("button", { name: "Race" }));
    expect(await screen.findByRole("heading", { name: "Pick a round" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Bahrain Grand Prix/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Saudi Arabian Grand Prix/ })).toBeTruthy();
  });

  it("doubles the points on a Coin Flip Round (LOW_CONSENSUS, engine-flagged)", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Saudi Arabian Grand Prix/ }));
    await screen.findByRole("region", { name: "Call sheet for Saudi Arabian Grand Prix" });
    for (const code of ["VER", "PER", "LEC"]) {
      fireEvent.click(screen.getByRole("button", { name: new RegExp(code) }));
    }
    fireEvent.click(screen.getByRole("button", { name: "LOCK IT" }));

    const reveal = await screen.findByRole("region", { name: /Reveal for Saudi Arabian Grand Prix/ });
    // 18 base points × 2 on the engine's LOW_CONSENSUS flag.
    expect(within(reveal).getByText("+36")).toBeTruthy();
    expect(within(reveal).getByText("COIN FLIP ×2")).toBeTruthy();
  });
});

describe("Model Gauntlet (engine-backed)", () => {
  let engine: MockEngine;

  afterEach(() => {
    cleanup();
    engine.restore();
  });

  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "";
    engine = installMockEngine();
  });

  it("renders You plus four competitors from stored engine scores once a round is played", async () => {
    render(<App />);
    await playBahrainPerfect();
    fireEvent.click(screen.getByRole("button", { name: "Models" }));

    const table = await screen.findByRole("table");
    for (const name of ["You", "m1-gbm", "m2-logit", "m3-form", "Ensemble"]) {
      expect(within(table).getByText(name)).toBeTruthy();
    }
    // The per-round consensus chips render for the played round.
    expect(screen.getByText(/Consensus by round/)).toBeTruthy();
  });

  it("renders the measured backtest from the served ledger", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Models" }));
    const panel = await screen.findByRole("region", { name: "Backtest accuracy" });
    // Numbers come from the BacktestRecord in /api/evidence — never invented.
    expect(within(panel).getAllByText("50%").length).toBeGreaterThan(0);
    expect(within(panel).getByText(/skipped for missing data/)).toBeTruthy();
  });

  it("shows the empty state before any round is played", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Models" }));
    expect(await screen.findByText(/No rounds played yet/)).toBeTruthy();
  });
});
