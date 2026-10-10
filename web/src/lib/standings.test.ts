import { describe, expect, it } from "vitest";
import { CALL_SHEETS } from "../fixtures/callsheets";
import { RECORDS_BY_RACE_ID } from "../fixtures/records";
import { emptyRecord } from "./pitwall";
import { podiumCall } from "./scoring";
import {
  COMPETITORS,
  COMPETITOR_NAMES,
  latestNearMiss,
  nearMiss,
  playedRounds,
  seasonStandings,
} from "./standings";
import type { PitWallRecord } from "../types";

const PERFECT_CALL = (() => {
  const order = CALL_SHEETS["austrian-gp"].finishingOrder;
  return { p1: order[0], p2: order[1], p3: order[2] };
})();

function recordWithCalls(calls: PitWallRecord["calls"]): PitWallRecord {
  return { ...emptyRecord(), calls };
}

describe("seasonStandings", () => {
  it("scores zero rounds for an empty record", () => {
    const standings = seasonStandings(emptyRecord());
    expect(standings).toHaveLength(5);
    for (const entry of standings) {
      expect(entry.points).toBe(0);
      expect(entry.roundsPlayed).toBe(0);
      expect(entry.exactHitRate).toBeNull();
    }
    // The player has no distribution, so no Brier score.
    expect(standings.find((e) => e.competitorId === "you")?.meanBrier).toBeNull();
  });

  it("scores the player's perfect call at the top of the table", () => {
    const flag = RECORDS_BY_RACE_ID["austrian-gp"].ensemble.consensus.flag;
    const expected = flag === "LOW_CONSENSUS" ? 36 : 18;
    const standings = seasonStandings(recordWithCalls({ "austrian-gp": PERFECT_CALL }));
    const you = standings.find((e) => e.competitorId === "you");
    expect(you?.points).toBe(expected);
    expect(you?.roundsPlayed).toBe(1);
    expect(you?.exactHitRate).toBe(1);
    expect(standings[0].competitorId).toBe("you");
  });

  it("scores every model and the ensemble alongside the player", () => {
    const standings = seasonStandings(recordWithCalls({ "austrian-gp": PERFECT_CALL }));
    // Output is rank-ordered by points; every competitor appears exactly once.
    expect(standings.map((e) => e.competitorId).sort()).toEqual([...COMPETITORS].sort());
    for (const entry of standings) {
      expect(entry.roundsPlayed).toBe(1);
      if (entry.competitorId !== "you") {
        expect(entry.meanBrier).not.toBeNull();
      }
    }
  });
});

describe("nearMiss", () => {
  it("names a P4 pick and whether the ensemble knew", () => {
    // Hamilton finished P4 in the Austrian fixture — picked into slot 3.
    const call = { ...PERFECT_CALL, p3: "44-ham" };
    const feedback = nearMiss("austrian-gp", call);
    expect(feedback).not.toBeNull();
    expect(feedback?.driverId).toBe("44-ham");
    expect(feedback?.pickedSlot).toBe(3);
    const ensemblePodium = podiumCall(RECORDS_BY_RACE_ID["austrian-gp"].ensemble.podium);
    expect(feedback?.ensembleKnew).toBe(
      [ensemblePodium?.p1, ensemblePodium?.p2, ensemblePodium?.p3].includes("44-ham"),
    );
  });

  it("returns null when no pick finished P4", () => {
    expect(nearMiss("austrian-gp", PERFECT_CALL)).toBeNull();
  });
});

describe("playedRounds / latestNearMiss", () => {
  it("lists played rounds with their consensus flag", () => {
    const played = playedRounds(recordWithCalls({ "austrian-gp": PERFECT_CALL }));
    expect(played).toEqual([
      {
        raceId: "austrian-gp",
        flag: RECORDS_BY_RACE_ID["austrian-gp"].ensemble.consensus.flag,
      },
    ]);
  });

  it("finds the latest near miss across played rounds", () => {
    const feedback = latestNearMiss(
      recordWithCalls({ "austrian-gp": { ...PERFECT_CALL, p3: "44-ham" } }),
    );
    expect(feedback?.driverId).toBe("44-ham");
  });

  it("returns null without any near miss", () => {
    expect(latestNearMiss(recordWithCalls({ "austrian-gp": PERFECT_CALL }))).toBeNull();
  });
});

describe("COMPETITOR_NAMES", () => {
  it("labels every competitor for the Gauntlet table", () => {
    expect(COMPETITORS.map((id) => COMPETITOR_NAMES[id])).toEqual([
      "You",
      "m1-gbm",
      "m2-logit",
      "m3-form",
      "Ensemble",
    ]);
  });
});
