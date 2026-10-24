import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "../App";
import { installMockEngine, type MockEngine } from "../test/mockEngine";

async function openPredictions() {
  render(<App />);
  return screen.findByRole("article", { name: "Prediction for 2024 Saudi Arabian Grand Prix" });
}

function chooseRace(label: RegExp) {
  const select = screen.getByRole("combobox", { name: "Race" }) as HTMLSelectElement;
  const option = within(select).getByRole("option", { name: label }) as HTMLOptionElement;
  fireEvent.change(select, { target: { value: option.value } });
}

describe("Race Predictions (anonymous, honest labels)", () => {
  let engine: MockEngine;

  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.location.hash = "";
    engine = installMockEngine();
  });

  afterEach(() => {
    cleanup();
    engine.restore();
  });

  it("opens on the latest supported race, labeled HISTORICAL with its cutoff and evidence", async () => {
    const article = await openPredictions();
    expect(within(article).getByText("HISTORICAL")).toBeTruthy();
    expect(await within(article).findByText("2023 Abu Dhabi Grand Prix (2023-11-26)")).toBeTruthy();
    expect(within(article).getByText("Replayed later; original time not recorded")).toBeTruthy();
    const table = within(article).getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0].textContent).toContain("Max Verstappen");
    expect(rows[0].textContent).toContain("30%");
    // Podium values are withheld, and the failed check is stated in words, not color.
    expect(within(table).queryByText(/podium/i)).toBeNull();
    expect(within(article).getByText("✕ Not shown: Podium probability")).toBeTruthy();
    expect(within(article).getByText("Failed:")).toBeTruthy();
    expect(within(article).getByText(/Blind guess|at random/)).toBeTruthy();
  });

  it("shows an explained unavailable state for a race without a prediction and never fetches one", async () => {
    await openPredictions();
    chooseRace(/Austrian Grand Prix/);
    const article = await screen.findByRole("article", { name: "Prediction for 2020 Austrian Grand Prix" });
    expect(within(article).getByText("UNAVAILABLE")).toBeTruthy();
    expect(within(article).getByText(/No prediction record for this round/)).toBeTruthy();
    expect(within(article).getByText(/Last verified data update/)).toBeTruthy();
    expect(engine.requests.some((url) => url.includes("austrian-grand-prix/prediction"))).toBe(false);
  });

  it("refuses the unsupported post-qualifying checkpoint instead of substituting another", async () => {
    await openPredictions();
    fireEvent.click(screen.getByRole("radio", { name: /After qualifying/ }));
    const article = screen.getByRole("article", { name: /Saudi Arabian Grand Prix/ });
    expect(within(article).getByText("UNAVAILABLE")).toBeTruthy();
    expect(within(article).getByText(/not that race's own qualifying/)).toBeTruthy();
    expect(within(article).queryByRole("table")).toBeNull();
    expect(engine.requests.some((url) => url.includes("checkpoint=post-qualifying"))).toBe(false);
  });

  it("degrades to a retryable error when the engine drops, then recovers", async () => {
    await openPredictions();
    engine.failAll();
    chooseRace(/Bahrain Grand Prix/);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/Can't reach the prediction engine|You're offline/)).toBeTruthy();
    engine.serve();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("table")).toBeTruthy();
  });

  it("reveals the actual winner only when asked", async () => {
    const article = await openPredictions();
    expect(within(article).queryByText(/Actual winner/)).toBeNull();
    fireEvent.click(await within(article).findByRole("button", { name: /Show how the prediction did/ }));
    expect(await within(article).findByText(/Actual winner/)).toBeTruthy();
  });

  it("writes nothing to cookies or browser storage while predicting and comparing", async () => {
    await openPredictions();
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    await screen.findByRole("heading", { name: "Teams" });
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });
});

describe("Compare, Performance, Data & Evidence, About", () => {
  let engine: MockEngine;

  beforeEach(() => {
    window.location.hash = "";
    engine = installMockEngine();
  });

  afterEach(() => {
    cleanup();
    engine.restore();
  });

  it("compares two drivers and adds team chances from their drivers", async () => {
    window.location.hash = "#/compare";
    render(<App />);
    const teams = await screen.findByRole("table", { name: /Each team's chance/ });
    const redBull = within(teams).getByRole("row", { name: /Red Bull/ });
    // Saudi mock: Verstappen 30% + Perez 23% = 53%.
    expect(redBull.textContent).toContain("53%");
    const inputs = screen.getByRole("table", { name: /Model inputs/ });
    expect(within(inputs).queryByText("No data")).toBeNull();
    fireEvent.change(screen.getByRole("combobox", { name: "Second driver" }), { target: { value: "hamilton" } });
    expect(within(inputs).getByText("No data")).toBeTruthy();
  });

  it("shows the executed evaluation next to the blind-guess baseline", async () => {
    window.location.hash = "#/models";
    render(<App />);
    expect(await screen.findByText("Blind guess (baseline)")).toBeTruthy();
    expect(screen.getByText(/Not established/)).toBeTruthy();
  });

  it("shows the data-quality profile with severities in words", async () => {
    window.location.hash = "#/evidence";
    render(<App />);
    expect(await screen.findByText("podium probabilities sum to about 3")).toBeTruthy();
    expect(screen.getByText("Warning")).toBeTruthy();
  });

  it("states the privacy model on the About page", async () => {
    window.location.hash = "#/about";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "No accounts, nothing saved about you" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Retention by kind of data" })).toBeTruthy();
    await waitFor(() => expect(document.cookie).toBe(""));
  });
});
