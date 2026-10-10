/**
 * Client unit tests against response fixtures that match the real pydantic
 * schemas (engine/f1engine/app.py wire shapes). The fail-closed contract is
 * the subject: every non-happy path surfaces as a typed ApiError.
 */

import { describe, expect, it } from "vitest";
import { createEngineClient } from "./api";
import { CONFIG, EVIDENCE_PAGE, RACES, RESULTS } from "../test/mockEngine";
import type { CallScore, EventsView, PredictionsView } from "../types";

/** Serve one canned response per call; return the client and its request log. */
function clientOver(handler: (url: string) => Response) {
  const requests: string[] = [];
  const fetchImpl = ((input: RequestInfo | URL): Promise<Response> => {
    const url = String(input);
    requests.push(url);
    return Promise.resolve(handler(url));
  }) as typeof fetch;
  return { client: createEngineClient(fetchImpl), requests };
}

/** An engine-style typed error body. */
const errorBody = (code: string, message: string) =>
  new Response(JSON.stringify({ detail: { code, message } }), {
    status: 400,
    headers: { "content-type": "application/json" },
  });

describe("engine client (typed, fail-closed)", () => {
  it("parses a well-formed view", async () => {
    const { client } = clientOver(
      () => new Response(JSON.stringify(RACES), { status: 200 }),
    );
    expect(await client.getRaces()).toEqual(RACES);
  });

  it("refuses a structurally wrong envelope as RESPONSE_INVALID", async () => {
    const { client } = clientOver(
      () => new Response(JSON.stringify({ unexpected: true }), { status: 200 }),
    );
    await expect(client.getRaces()).rejects.toMatchObject({ code: "RESPONSE_INVALID" });
  });

  it("carries the engine's typed detail code and status", async () => {
    const { client } = clientOver(() => errorBody("RACE_UNKNOWN", "no such race"));
    await expect(client.getPredictions("nowhere-gp", 2024)).rejects.toMatchObject({
      code: "RACE_UNKNOWN",
      message: "no such race",
      status: 400,
    });
  });

  it("degrades an unknown engine code to RESPONSE_NOT_OK — no lying cast", async () => {
    const { client } = clientOver(() => errorBody("SOME_FUTURE_CODE", "newer engine"));
    await expect(client.getRaces()).rejects.toMatchObject({
      code: "RESPONSE_NOT_OK",
      message: /SOME_FUTURE_CODE|newer engine/,
    });
  });

  it("degrades a non-JSON error body to RESPONSE_NOT_OK", async () => {
    const { client } = clientOver(
      () => new Response("<html>gateway timeout</html>", { status: 504 }),
    );
    await expect(client.getRaces()).rejects.toMatchObject({
      code: "RESPONSE_NOT_OK",
      status: 504,
    });
  });

  it("surfaces transport failure as ENGINE_UNREACHABLE", async () => {
    const fetchImpl = (() => Promise.reject(new TypeError("Failed to fetch"))) as typeof fetch;
    const client = createEngineClient(fetchImpl);
    await expect(client.getConfig()).rejects.toMatchObject({ code: "ENGINE_UNREACHABLE" });
  });

  it("encodes the score request as call, streak_before and season", async () => {
    const score: CallScore = {
      round: {
        picks: [
          { slot: "p1", driverId: "max_verstappen", actualPosition: 1, outcome: "EXACT", points: 5 },
          { slot: "p2", driverId: "leclerc", actualPosition: 2, outcome: "EXACT", points: 5 },
          { slot: "p3", driverId: "perez", actualPosition: 3, outcome: "EXACT", points: 5 },
        ],
        basePoints: 18,
        consensusFlag: "OK",
        coinFlip: false,
        totalPoints: 18,
      },
      streak: { before: 4, after: 5, delta: 1, flame: true },
    };
    const { client, requests } = clientOver(
      () => new Response(JSON.stringify(score), { status: 200 }),
    );
    const served = await client.getRaceScore("bahrain-gp", ["max_verstappen", "leclerc", "perez"], 4, 2024);
    expect(served).toEqual(score);
    expect(requests.at(-1)).toBe(
      "/api/races/bahrain-gp/score?call=max_verstappen,leclerc,perez&streak_before=4&season=2024",
    );
  });

  it("serves the prediction and result views season-qualified", async () => {
    const predictions: PredictionsView = { predictions: [], total: 0 };
    const { client, requests } = clientOver((url) => {
      if (url.includes("/api/predictions")) {
        return new Response(JSON.stringify(predictions), { status: 200 });
      }
      return new Response(JSON.stringify(RESULTS["bahrain-gp"]), { status: 200 });
    });
    await client.getPredictions("bahrain-gp", 2024);
    expect(requests[0]).toBe("/api/predictions/bahrain-gp?season=2024");
    expect(await client.getRaceResult("bahrain-gp", 2024)).toEqual(RESULTS["bahrain-gp"]);
    expect(requests[1]).toBe("/api/races/bahrain-gp/result?season=2024");
  });

  it("serves the event feed and metrics verbatim", async () => {
    const events: EventsView = { events: [], total: 0 };
    const { client } = clientOver((url) =>
      url.startsWith("/metrics")
        ? new Response("# HELP f1engine_up 1\n", { status: 200 })
        : new Response(JSON.stringify(events), { status: 200 }),
    );
    expect(await client.getMetrics()).toBe("# HELP f1engine_up 1\n");
    expect(await client.getEvents()).toEqual(events);
  });

  it("extracts the backtest record from the evidence page, null when absent", async () => {
    const { client } = clientOver(
      () => new Response(JSON.stringify(EVIDENCE_PAGE), { status: 200 }),
    );
    expect((await client.getBacktest())?.recordType).toBe("backtest");

    const { client: without } = clientOver(
      () =>
        new Response(
          JSON.stringify({
            ...EVIDENCE_PAGE,
            records: EVIDENCE_PAGE.records.filter((r) => r.recordType !== "backtest"),
          }),
          { status: 200 },
        ),
    );
    expect(await without.getBacktest()).toBeNull();
  });

  it("sends the accept header the engine contract expects", async () => {
    const captured = { headers: null as Headers | null };
    const fetchImpl = ((_input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      captured.headers = new Headers(init?.headers);
      return Promise.resolve(new Response(JSON.stringify(CONFIG), { status: 200 }));
    }) as typeof fetch;
    await createEngineClient(fetchImpl).getConfig();
    expect(captured.headers?.get("accept")).toBe("application/json");
  });
});
