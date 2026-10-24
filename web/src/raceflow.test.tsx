import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    window.location.hash = "#/race";
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

  it("keeps the pit-wall record in memory only: nothing stored, and a reload starts fresh", async () => {
    window.localStorage.setItem("unrelated-key", "keep");
    const first = render(<App />);
    await playBahrainPerfect();
    // Nothing about the player reached browser storage.
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(Object.keys(window.localStorage)).toEqual(["unrelated-key"]);
    expect(Object.keys(window.sessionStorage)).toEqual([]);
    first.unmount();

    // "Reload": a fresh App instance starts with an empty record.
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Rewind" }));
    await screen.findByRole("heading", { name: "Pick a round" });
    expect(screen.queryByText("PLAYED")).toBeNull();
  });

  it("removes a record stored by an earlier build on startup", async () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ profileName: "KG", streak: 4 }));
    render(<App />);
    await waitFor(() => expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull());
  });

  it("hides played rounds when Fresh Eyes is on", async () => {
    render(<App />);
    await playBahrainPerfect();

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const toggle = await screen.findByLabelText(/Fresh Eyes/i);
    fireEvent.click(toggle);

    fireEvent.click(screen.getByRole("button", { name: "Rewind" }));
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
    window.location.hash = "#/race";
    engine = installMockEngine();
  });

  it("renders You plus four competitors from stored engine scores once a round is played", async () => {
    render(<App />);
    await playBahrainPerfect();
    fireEvent.click(screen.getByRole("button", { name: "Performance" }));

    const table = await screen.findByRole("table", { name: "Rewind standings" });
    for (const name of ["You", "m1-gbm", "m2-logit", "m3-form", "Ensemble"]) {
      expect(within(table).getByText(name)).toBeTruthy();
    }
    // The per-round consensus chips render for the played round.
    expect(screen.getByText(/Consensus by round/)).toBeTruthy();
  });

  it("renders the measured backtest from the served ledger", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Performance" }));
    const panel = await screen.findByRole("region", { name: "Backtest accuracy" });
    // Numbers come from the BacktestRecord in /api/evidence — never invented.
    // Shown as a fraction of rounds, with the percentage as a footnote.
    expect(within(panel).getAllByText("1 of 2 (50%)").length).toBeGreaterThan(0);
    expect(within(panel).getByText(/skipped for missing data/)).toBeTruthy();
  });

  it("shows a blind-guess baseline under the backtest so the numbers have a reference", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Performance" }));
    const panel = await screen.findByRole("region", { name: "Backtest accuracy" });
    const baseline = within(panel).getByText("Blind guess").closest("tr");
    expect(baseline).toBeTruthy();
    expect(within(baseline as HTMLElement).getByText("≈5%")).toBeTruthy();
    expect(within(baseline as HTMLElement).getByText("0.95")).toBeTruthy();
  });

  it("shows the empty state before any round is played", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Performance" }));
    expect(await screen.findByText(/No rounds played yet/)).toBeTruthy();
  });
});
