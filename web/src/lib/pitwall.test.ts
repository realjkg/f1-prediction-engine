import { beforeEach, describe, expect, it } from "vitest";
import {
  browserStorage,
  clearRecord,
  emptyRecord,
  hydrate,
  loadRecord,
  saveRecord,
} from "./pitwall";

describe("hydrate", () => {
  it("returns an empty record for non-objects", () => {
    expect(hydrate(null)).toEqual(emptyRecord());
    expect(hydrate("garbage")).toEqual(emptyRecord());
  });

  it("keeps valid calls and drops malformed ones", () => {
    const record = hydrate({
      calls: {
        "r1": { p1: "a", p2: "b", p3: "c" },
        "bad": { p1: "a", p2: 42 },
      },
    });
    expect(Object.keys(record.calls)).toEqual(["r1"]);
  });

  it("preserves the dataset digest binding on a stored call", () => {
    const record = hydrate({
      calls: { "r1": { p1: "a", p2: "b", p3: "c", datasetDigest: "deadbeef" } },
    });
    expect(record.calls.r1?.datasetDigest).toBe("deadbeef");
  });

  it("defaults missing counters and coerces wrong types", () => {
    const record = hydrate({ streak: "three", evidenceViews: "many" });
    expect(record.streak).toBe(0);
    expect(record.evidenceViews).toBe(0);
    expect(record.freshEyes).toBe(false);
  });
});

describe("loadRecord / saveRecord / clearRecord", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("round-trips a record through localStorage", () => {
    const storage = browserStorage();
    const record = {
      ...emptyRecord(),
      profileName: "KG",
      calls: { "r1": { p1: "a", p2: "b", p3: "c" } },
      streak: 1,
      evidenceViews: 2,
    };
    saveRecord(storage, record);
    expect(loadRecord(storage)).toEqual(record);
  });

  it("starts clean when nothing is stored", () => {
    expect(loadRecord(browserStorage())).toEqual(emptyRecord());
  });

  it("starts clean on corrupt JSON instead of crashing", () => {
    window.localStorage.setItem("pitwall.record.v1", "{not json");
    expect(loadRecord(browserStorage())).toEqual(emptyRecord());
  });

  it("clears the stored record", () => {
    const storage = browserStorage();
    saveRecord(storage, { ...emptyRecord(), profileName: "KG" });
    clearRecord(storage);
    expect(loadRecord(storage)).toEqual(emptyRecord());
  });
});
