import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AdvisoryBanner } from "../components/AdvisoryBanner";
import type { ConfigView, LiveStatusView } from "../types";
import { ConfigProvider, LiveNowProvider, advisoryBasis } from "./engine";
import { isLive, liveWord } from "./live";

const status = (over: Partial<LiveStatusView> = {}): LiveStatusView => ({
  feedState: "connected", evidenceState: "fresh-checkpoint",
  inferenceState: "conditional-research", season: 2026, raceId: "x", broker: "openf1",
  lastMessageAt: null, lastCheckpointAt: null, lap: 5, totalLaps: 60,
  sourceType: "licensed-live", checkpointSha256: null,
  qualifiedForProduction: false, modelPromoted: false, ...over,
});

const config: ConfigView = {
  engineVersion: "0.1.0", datasetVersion: "2026.10.0", advisoryOnly: true,
  advisoryNotice: "", consensusThreshold: 0.15, briefMode: "fixture",
};

afterEach(cleanup);

describe("Live / Not live", () => {
  it("is live only for a connected feed with a fresh licensed checkpoint", () => {
    expect(isLive(status())).toBe(true);
    expect(isLive(status({ feedState: "stale" }))).toBe(false);
    expect(isLive(status({ feedState: "offline" }))).toBe(false);
    expect(isLive(status({ evidenceState: "stale-checkpoint" }))).toBe(false);
    expect(isLive(status({ evidenceState: "replay" }))).toBe(false);
    expect(isLive(status({ sourceType: "synthetic-fixture" }))).toBe(false);
    expect(isLive(null)).toBe(false);
    expect(isLive(undefined)).toBe(false);
  });

  it("uses the two plain words, never the old phrasing", () => {
    expect(liveWord(true)).toBe("LIVE");
    expect(liveWord(false)).toBe("NOT LIVE");
    expect(advisoryBasis(config)).toMatch(/— NOT LIVE$/);
    expect(advisoryBasis(config, true)).toMatch(/— LIVE$/);
    expect(advisoryBasis(config)).not.toMatch(/INFERENCE/);
  });

  it("the banner follows the live context", () => {
    const view = (live: boolean) => (
      <ConfigProvider value={{ status: "ready", config }}>
        <LiveNowProvider value={live}><AdvisoryBanner /></LiveNowProvider>
      </ConfigProvider>
    );
    const { rerender } = render(view(false));
    expect(screen.getByRole("note").textContent).toMatch(/NOT LIVE$/);
    rerender(view(true));
    expect(screen.getByRole("note").textContent).toMatch(/— LIVE$/);
  });
});
