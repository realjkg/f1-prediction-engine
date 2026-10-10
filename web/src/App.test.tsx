import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "./App";
import { installMockEngine, type MockEngine } from "./test/mockEngine";

const TAB_LABELS = ["Race", "Models", "Evidence", "Brief", "Observability", "Settings"];

describe("App shell (engine-backed)", () => {
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

  it("renders the six-tab bottom navigation with the round picker as the default route", async () => {
    render(<App />);
    const tabs = await waitFor(() => within(screen.getByRole("navigation")).getAllByRole("button"));
    expect(tabs.map((tab) => tab.textContent)).toEqual(TAB_LABELS);
    // The picker waits for the engine catalog, then renders.
    expect(await screen.findByRole("heading", { name: "Pick a round" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: /Bahrain Grand Prix/ })).toBeTruthy();
  });

  it("switches panels when a tab is pressed", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Pick a round" });
    fireEvent.click(screen.getByRole("button", { name: "Models" }));
    expect(screen.getByRole("heading", { name: "Model Gauntlet" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Pick a round" })).toBeNull();
  });

  it("carries the advisory evidence-basis banner from the served config", async () => {
    render(<App />);
    // briefMode "fixture" — the banner is the fixture variant, never hardcoded.
    expect(await screen.findAllByText(/PINNED DATASET/)).not.toHaveLength(0);
  });

  it("renders the typed engine-unreachable surface with retry, and recovers", async () => {
    engine.failAll();
    render(<App />);
    const panel = await screen.findByRole("alert");
    expect(panel.getAttribute("data-error-code")).toBe("ENGINE_UNREACHABLE");
    expect(within(panel).getByText(/Engine configuration — error/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Pick a round" })).toBeNull();

    // The engine comes back; retry renders the real picker — no stale state.
    engine.serve();
    fireEvent.click(within(panel).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Pick a round" })).toBeTruthy();
  });
});
