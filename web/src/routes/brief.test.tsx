import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "../App";
import { RACES, installMockEngine, type MockEngine } from "../test/mockEngine";

describe("Brief screen", () => {
  let engine: MockEngine;

  afterEach(() => {
    cleanup();
    engine.restore();
  });

  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "";
    engine = installMockEngine();

    // Mirror the real engine: the catalog spans seasons the ledger never scored.
    const served = globalThis.fetch;
    const longAgo = { season: 2020, round: 1, raceId: "austrian-grand-prix", name: "Austrian Grand Prix", date: "2020-07-05", completed: true };
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (new URL(url, "http://localhost").pathname === "/api/races") {
        const body = { races: [longAgo, ...RACES.races], total: RACES.races.length + 1 };
        return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return served(input, init);
    }) as typeof fetch;
  });

  it("lists only rounds that have a prediction record and opens on a working one", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Brief" }));

    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["2024 R1", "2024 R2"]);
    expect(screen.queryByRole("tab", { name: "2020 R1" })).toBeNull();

    // Opens on the latest covered round, with no error panel on first load.
    expect(tabs[1].getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(within(screen.getByRole("region", { name: "Race brief" })).queryByText(/PREDICTIONS_NOT_FOUND/)).toBeNull();
  });
});
