import { useState } from "react";
import { CallSheetView } from "../components/CallSheetView";
import { RacePicker } from "../components/RacePicker";
import { RevealView } from "../components/RevealView";
import { AdvisoryBanner } from "../components/AdvisoryBanner";
import { CALL_SHEETS } from "../fixtures/callsheets";
import { RACES, raceById } from "../fixtures/races";
import { RECORDS_BY_RACE_ID } from "../fixtures/records";
import { badgesForRound } from "../lib/badges";
import { nearMiss, seasonStandings } from "../lib/standings";
import { scoreRound } from "../lib/scoring";
import type { PitWallRecord, RoundCall } from "../types";

interface RacePageProps {
  record: PitWallRecord;
  /** Persists the call and updates streak/badges — the engine mirror lives in App. */
  onLock: (raceId: string, call: RoundCall) => void;
  onOpenEvidence: () => void;
}

type Stage = "picker" | "sheet" | "reveal";

/**
 * The Race Rewind loop: pick a round → the call sheet → lock → the reveal.
 * Stage is local; the pit-wall record lives above (it survives reloads).
 */
export function RacePage({ record, onLock, onOpenEvidence }: RacePageProps) {
  const [stage, setStage] = useState<Stage>("picker");
  const [raceId, setRaceId] = useState<string | null>(null);
  const [call, setCall] = useState<RoundCall | null>(null);

  if (stage === "picker" || raceId == null) {
    return (
      <RacePicker
        record={record}
        onPick={(picked) => {
          setRaceId(picked);
          setCall(null);
          setStage("sheet");
        }}
      />
    );
  }

  const race = raceById(raceId);
  const sheet = CALL_SHEETS[raceId];
  const predictionRecord = RECORDS_BY_RACE_ID[raceId];
  if (!race || !sheet || !predictionRecord) {
    // A catalog entry without a sheet/record is a fixture inconsistency — fail loudly, never silently.
    throw new Error(`Fixture inconsistency: no call sheet or prediction record for ${raceId}`);
  }

  if (stage === "sheet") {
    return (
      <>
        <AdvisoryBanner />
        <CallSheetView
          raceName={race.name}
          season={race.season}
          round={race.round}
          sheet={sheet}
          datasetDigest={predictionRecord.dataset.sha256}
          onLock={(locked) => {
            onLock(raceId, locked);
            setCall(locked);
            setStage("reveal");
          }}
        />
      </>
    );
  }

  // Stage is "reveal" here; a reveal without a locked call is a state
  // machine bug — fail loudly rather than render a null card.
  if (call == null) {
    throw new Error("Reveal without a locked call — state machine inconsistency");
  }

  // Reveal — every number derives from the scoring mirror over the fixture data.
  const flag = predictionRecord.ensemble.consensus.flag;
  const score = scoreRound(call, sheet.finishingOrder, flag);
  const standings = seasonStandings(record);
  const earned = badgesForRound({
    exactPodium: score.positionExactCount === 3,
    winnerCalled: score.winnerBonus,
    streakAfterRound: record.streak,
    playerPoints: standings.find((entry) => entry.competitorId === "you")?.points ?? 0,
    ensemblePoints: standings.find((entry) => entry.competitorId === "ensemble")?.points ?? 0,
    winnerProb: predictionRecord.ensemble.winner[call.p1] ?? null,
    p2OnPodium: positionOf(sheet, call.p2) <= 3,
    p3OnPodium: positionOf(sheet, call.p3) <= 3,
    evidenceViews: record.evidenceViews,
  });
  const miss = nearMiss(raceId, call);
  const nextRaceId = nextUnplayedAfter(raceId, record);

  return (
    <RevealView
      race={race}
      sheet={sheet}
      record={predictionRecord}
      call={call}
      score={score}
      streakAfter={record.streak}
      nearMissFeedback={miss}
      badgesEarned={earned}
      onNextRound={
        nextRaceId
          ? () => {
              setRaceId(nextRaceId);
              setCall(null);
              setStage("sheet");
            }
          : null
      }
      onOpenEvidence={onOpenEvidence}
    />
  );
}

function positionOf(sheet: { finishingOrder: string[] }, driverId: string): number {
  const index = sheet.finishingOrder.indexOf(driverId);
  return index < 0 ? Number.POSITIVE_INFINITY : index + 1;
}

/** The next catalog round without a call — one tap continues the loop. */
function nextUnplayedAfter(raceId: string, record: PitWallRecord): string | null {
  const index = RACES.findIndex((race) => race.raceId === raceId);
  return (
    RACES.slice(index + 1)
      .find((race) => record.calls[race.raceId] == null)
      ?.raceId ?? null
  );
}
