import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "./App";
import { installMockEngine, type MockEngine } from "./test/mockEngine";

const TAB_LABELS = ["Race", "Live Lab", "Models", "Evidence", "Brief", "Observability", "Inventory", "Settings"];

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

  it("renders the eight-tab bottom navigation with the round picker as the default route", async () => {
    render(<App />);
    const tabs = await waitFor(() => within(screen.getByRole("navigation")).getAllByRole("button"));
    expect(tabs.map((tab) => tab.textContent)).toEqual(TAB_LABELS);
    // The picker waits for the engine catalog, then renders.
    expect(await screen.findByRole("heading", { name: "Pick a round" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: /Bahrain Grand Prix/ })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Race Rewind animated warm-up" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Pause cars" })).toBeTruthy();
  });

  it("switches panels when a tab is pressed", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Pick a round" });
    fireEvent.click(screen.getByRole("button", { name: "Models" }));
    expect(screen.getByRole("heading", { name: "Model Gauntlet" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Pick a round" })).toBeNull();
  });

  it("labels the live lab as research and refuses unsupported scenario data", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Pick a round" });
    fireEvent.click(screen.getByRole("button", { name: "Live Lab" }));
    expect(screen.getByRole("heading", { name: "In-race Lab" })).toBeTruthy();
    expect(screen.getByText(/Scenario frequencies are not calibrated/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "Live feed and inference status" })).toBeTruthy();
    expect(screen.getByText(/Manual or 15-second polling; not a live stream/)).toBeTruthy();
    expect(await screen.findByText(/no simulation to show/i)).toBeTruthy();
  });

  it("refuses to declare live release ready when supply chain and accuracy evidence are missing", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Pick a round" });
    fireEvent.click(screen.getByRole("button", { name: "Inventory" }));
    expect(await screen.findByRole("heading", { name: "Software inventory & release checks" })).toBeTruthy();
    expect(await screen.findByText(/The inventory is unavailable until its generated artifact/)).toBeTruthy();
    expect(screen.getByText(/Production live prediction: NOT QUALIFIED/)).toBeTruthy();
    expect(screen.getByText("No verified evaluation report")).toBeTruthy();
    expect(screen.getByText("Unavailable", { selector: ".supply-gate-state" })).toBeTruthy();
  });

  it("shows verified partial dependency evidence without claiming a production release", async () => {
    const previousFetch = globalThis.fetch;
    const inventory = {
      status: "lockfile-inventory-only", specVersion: "1.6",
      sbomSha256: "a".repeat(64),
      sourceDigests: { "web/package-lock.json": "b".repeat(64) },
      totalComponents: 2, ecosystemCounts: { pypi: 1, npm: 1 },
      releaseReady: false, limitations: ["Container OS and native libraries excluded"],
      components: [
        { ecosystem: "pypi", name: "fastapi", version: "0.143.0", scope: "required", license: null },
        { ecosystem: "npm", name: "react", version: "19.3.0", scope: "required", license: "MIT" },
      ],
    };
    const fetchWithInventory = ((input: RequestInfo | URL, init?: RequestInit) => {
      if (new URL(String(input), "http://test").pathname === "/api/supply-chain") {
        return Promise.resolve(new Response(JSON.stringify(inventory), { status: 200 }));
      }
      return previousFetch(input, init);
    }) as typeof fetch;
    globalThis.fetch = fetchWithInventory;
    (window as unknown as { fetch: typeof fetch }).fetch = fetchWithInventory;

    render(<App />);
    await screen.findByRole("heading", { name: "Pick a round" });
    fireEvent.click(screen.getByRole("button", { name: "Inventory" }));
    expect(await screen.findByText("Verified — partial SBOM")).toBeTruthy();
    expect(screen.getByText(/Production live prediction: NOT QUALIFIED/)).toBeTruthy();
    expect(screen.getByText("fastapi")).toBeTruthy();
    expect(screen.getByText("react")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox", { name: "Find a package" }), {
      target: { value: "fastapi" },
    });
    expect(screen.getByText("Showing 1 of 2 packages.")).toBeTruthy();
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
