import { useState } from "react";
import { CallSheetView } from "../components/CallSheetView";
import { RacePicker } from "../components/RacePicker";
import { RevealView } from "../components/RevealView";
import { AdvisoryBanner } from "../components/AdvisoryBanner";
import { ResourceView } from "../components/EngineError";
import { ApiError, asApiError, type EngineClient } from "../lib/api";
import { useEngineClient, useResource } from "../lib/engine";
import { driverName } from "../lib/drivers";
import type {
  CallScore,
  LockOutcome,
  PredictionRecord,
  PitWallRecord,
  RaceIdentity,
  RaceSummary,
  RoundCall,
} from "../types";
import { raceKeyOf } from "../types";

interface RacePageProps {
  record: PitWallRecord;
  /**
   * Locks the call through the engine (scores the player AND every
   * competitor's podium call) and persists the result. Throws on failure —
   * nothing is stored.
   */
  onLock: (race: RaceIdentity, call: RoundCall, predictionRecord: PredictionRecord) => Promise<LockOutcome>;
  onOpenEvidence: () => void;
}

type Stage = "sheet" | "reveal";

/**
 * The Race Rewind loop: pick a round (the engine catalog) → the call sheet
 * → lock (engine-scored) → the reveal. The picked round is keyed into the
 * flow below, so per-round resources and picks reset cleanly on next-round.
 */
export function RacePage({ record, onLock, onOpenEvidence }: RacePageProps) {
  const client = useEngineClient();
  const [picked, setPicked] = useState<RaceSummary | null>(null);

  return (
    <ResourceView
      resource={useResource(() => client.getRaces(), [])}
      context="Race catalog"
      ready={(catalog) =>
        picked == null ? (
          <RacePicker races={catalog.races} record={record} onPick={setPicked} />
        ) : (
          <RoundFlow
            key={raceKeyOf(picked.season, picked.round, picked.raceId)}
            client={client}
            race={picked}
            record={record}
            onLock={onLock}
            onOpenEvidence={onOpenEvidence}
            onBackToPicker={() => setPicked(null)}
            onPickRace={setPicked}
            races={catalog.races}
          />
        )
      }
    />
  );
}

interface RoundFlowProps {
  client: EngineClient;
  race: RaceSummary;
  record: PitWallRecord;
  onLock: RacePageProps["onLock"];
  onOpenEvidence: () => void;
  onBackToPicker: () => void;
  onPickRace: (race: RaceSummary) => void;
  races: RaceSummary[];
}

/**
 * One picked round: predictions load for the call sheet, the lock scores
 * through the engine, the result loads for the reveal. State is per-round —
 * the parent keys this component by the season-qualified race key.
 */
function RoundFlow({
  client,
  race,
  record,
  onLock,
  onOpenEvidence,
  onBackToPicker,
  onPickRace,
  races,
}: RoundFlowProps) {
  const [stage, setStage] = useState<Stage>("sheet");
  const [call, setCall] = useState<RoundCall | null>(null);
  const [score, setScore] = useState<CallScore | null>(null);
  const [badgesEarned, setBadgesEarned] = useState<LockOutcome["badgesEarned"]>([]);
  const [locking, setLocking] = useState(false);
  const [lockError, setLockError] = useState<ApiError | null>(null);

  const raceIdentity: RaceIdentity = {
    season: race.season,
    round: race.round,
    raceId: race.raceId,
    name: race.name,
  };

  const predictions = useResource(
    () => client.getPredictions(race.raceId, race.season),
    [race.raceId, race.season],
  );
  // The result is only fetched once the reveal needs it — never during the call.
  const result = useResource(
    () => (stage === "reveal" ? client.getRaceResult(race.raceId, race.season) : Promise.resolve(null)),
    [stage, race.raceId, race.season],
  );

  const predictionRecord: PredictionRecord | null =
    predictions.status === "ready" ? (predictions.data.predictions[0] ?? null) : null;

  const handleLock = (locked: RoundCall) => {
    if (!predictionRecord) return;
    setLocking(true);
    setLockError(null);
    onLock(raceIdentity, locked, predictionRecord)
      .then((outcome) => {
        setCall(locked);
        setScore(outcome.score);
        setBadgesEarned(outcome.badgesEarned);
        setStage("reveal");
      })
      .catch((error: unknown) => {
        // The lock failed — keep the sheet and every pick in place; the
        // engine's typed error renders inline above the lock button.
        setLockError(asApiError(error));
      })
      .finally(() => setLocking(false));
  };

  const nextRace = nextUnplayedAfter(races, race, record);

  if (stage === "sheet" || call == null || score == null) {
    return (
      <>
        <AdvisoryBanner />
        <ResourceView
          resource={predictions}
          context="Prediction record"
          ready={() => {
            if (!predictionRecord) {
              return (
                <div className="engine-error" role="alert">
                  <p className="engine-error-headline">
                    The engine served no prediction record for this round.
                  </p>
                  <button type="button" className="secondary-button" onClick={onBackToPicker}>
                    Back to rounds
                  </button>
                </div>
              );
            }
            return (
              <CallSheetView
                raceName={race.name}
                season={race.season}
                round={race.round}
                entrants={fieldEntrants(predictionRecord)}
                datasetDigest={predictionRecord.dataset.sha256}
                locking={locking}
                lockError={lockError}
                onLock={handleLock}
              />
            );
          }}
        />
        <button type="button" className="secondary-button back-to-picker" onClick={onBackToPicker}>
          ← All rounds
        </button>
      </>
    );
  }

  // Reveal: locked call and engine score in hand; the classified result loads here.
  if (predictionRecord == null) {
    // Unreachable in practice — a lock requires the prediction record — but
    // the typechecker is right that it could have unloaded.
    return <p className="empty-state">The prediction record is no longer loaded — pick the round again.</p>;
  }
  return (
    <ResourceView
      resource={result}
      context="Classified result"
      ready={(resultView) =>
        resultView == null ? (
          <p className="empty-state">Loading the classified result…</p>
        ) : (
          <RevealView
            race={raceIdentity}
            record={predictionRecord}
            result={resultView}
            call={call}
            score={score}
            badgesEarned={badgesEarned}
            onNextRound={nextRace ? () => onPickRace(nextRace) : null}
            onOpenEvidence={onOpenEvidence}
          />
        )
      }
    />
  );
}

/**
 * The field the models scored — every driver in the record's distributions,
 * name-sorted for a stable sheet. This is the entrant list the engine's
 * features saw; no grid order is served over HTTP.
 */
function fieldEntrants(predictionRecord: PredictionRecord): string[] {
  const driverIds = new Set<string>([
    ...Object.keys(predictionRecord.ensemble.podium),
    ...Object.keys(predictionRecord.ensemble.winner),
  ]);
  return [...driverIds].sort((a, b) => driverName(a).localeCompare(driverName(b)));
}

/** The next catalog round without a call — one tap continues the loop. */
function nextUnplayedAfter(
  races: RaceSummary[],
  current: RaceSummary,
  record: PitWallRecord,
): RaceSummary | null {
  const index = races.findIndex(
    (race) =>
      race.season === current.season && race.round === current.round && race.raceId === current.raceId,
  );
  return (
    races
      .slice(index + 1)
      .find((race) => record.calls[raceKeyOf(race.season, race.round, race.raceId)] == null) ?? null
  );
}
