import { driverCode, driverName } from "../lib/drivers";
import { COMPETITOR_COLORS } from "../lib/colors";
import { podiumCall, topPicks } from "../lib/calls";
import type {
  BadgeId,
  CallScore,
  PredictionRecord,
  RaceIdentity,
  RaceResultView,
  RoundCall,
} from "../types";
import { ConsensusChip } from "./ConsensusChip";
import { Confetti } from "./Confetti";
import { FinishOrderReplay } from "./FinishOrderReplay";
import { ModelCard } from "./ModelCard";
import { ReplayDots } from "./ReplayDots";
import { RoundScoreCard } from "./RoundScoreCard";

interface RevealViewProps {
  race: RaceIdentity;
  /** The prediction record the round was called against. */
  record: PredictionRecord;
  /** The classified result — the engine's own. */
  result: RaceResultView;
  call: RoundCall;
  /** The engine-computed score of this round's lock. */
  score: CallScore;
  badgesEarned: BadgeId[];
  /** Null when every round is played — the loop closes on the picker. */
  onNextRound: (() => void) | null;
  onOpenEvidence: () => void;
}

/**
 * The headline for a scored round. A zero-point round only claims "the machine
 * saw it coming" when the ensemble's podium call really held a driver who
 * finished on the podium; otherwise the honest line is that nobody saw it.
 */
export function revealHeadline(round: CallScore["round"], machineHadPodiumDriver: boolean): string {
  if (round.picks.every((pick) => pick.outcome === "EXACT")) return "EXACT PODIUM";
  if (round.picks.some((pick) => pick.slot === "p1" && pick.outcome === "EXACT")) {
    return "WINNER CALLED";
  }
  if (round.totalPoints > 0) return "ON THE BOARD";
  return machineHadPodiumDriver ? "THE MACHINE SAW IT COMING" : "NOBODY SAW THAT COMING";
}

function ActualPodium({ result }: { result: RaceResultView }) {
  return (
    <ol className="actual-podium">
      {result.podium.map((driverId, index) => (
        <li key={driverId}>
          <span className="podium-slot">P{index + 1}</span>
          <span className="podium-driver">
            <span className="driver-code">{driverCode(driverId)}</span>
            {driverName(driverId)}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** The reveal — your call vs the actual result vs every model's card. */
export function RevealView({
  race,
  record,
  result,
  call,
  score,
  badgesEarned,
  onNextRound,
  onOpenEvidence,
}: RevealViewProps) {
  const landed: Record<string, number> = Object.fromEntries(
    result.classified.map((finish) => [finish.driverId, finish.position]),
  );
  const nearMissPick = score.round.picks.find((pick) => pick.outcome === "NEAR_MISS");
  const ensembleCall = podiumCall(record.ensemble.podium);
  const ensembleKnew =
    nearMissPick != null &&
    ensembleCall != null &&
    [ensembleCall.p1, ensembleCall.p2, ensembleCall.p3].includes(nearMissPick.driverId);
  const exact = score.round.picks.every((pick) => pick.outcome === "EXACT");
  const machineHadPodiumDriver =
    ensembleCall != null &&
    [ensembleCall.p1, ensembleCall.p2, ensembleCall.p3].some((driverId) => result.podium.includes(driverId));

  return (
    <section className="reveal" aria-label={`Reveal for ${race.name}`}>
      <Confetti show={exact} />
      <header className="reveal-head">
        <p className="reveal-kicker">{race.name}</p>
        <h1 className={`reveal-headline${exact ? " is-exact" : ""}`}>{revealHeadline(score.round, machineHadPodiumDriver)}</h1>
        {score.round.consensusFlag && <ConsensusChip flag={score.round.consensusFlag} coinFlip />}
        <p className="reveal-hindsight">Open replay — the models never saw this result; you may remember it.</p>
      </header>

      <FinishOrderReplay result={result} />

      <section className="actual-result" aria-label="Actual result">
        <h2>Actual podium</h2>
        <ActualPodium result={result} />
      </section>

      <ReplayDots distribution={record.ensemble.winner} actualWinnerId={result.podium[0]} />

      <div className="reveal-cards">
        <ModelCard
          title="Your call"
          highlight
          accent={COMPETITOR_COLORS.you}
          call={call}
          winPick={null}
          landed={landed}
          footer={<p className="card-when">Locked {call.lockedAt ?? "—"}</p>}
        />
        <ModelCard
          title="Ensemble"
          subtitle="weighted blend"
          accent={COMPETITOR_COLORS.ensemble}
          call={podiumCall(record.ensemble.podium)}
          winPick={topPicks(record.ensemble.winner, 1)[0] ?? null}
          landed={landed}
        />
        {(["m1-gbm", "m2-logit", "m3-form"] as const).map((modelId) => (
          <ModelCard
            key={modelId}
            title={modelId}
            accent={COMPETITOR_COLORS[modelId]}
            call={podiumCall(record.models[modelId].podium)}
            winPick={topPicks(record.models[modelId].winner, 1)[0] ?? null}
            landed={landed}
          />
        ))}
      </div>

      <RoundScoreCard round={score.round} streak={score.streak} badgesEarned={badgesEarned} />

      {nearMissPick && (
        <p className="near-miss" role="status">
          Your P{Number.parseInt(nearMissPick.slot.slice(1), 10)} {driverName(nearMissPick.driverId)} finished P4
          {ensembleKnew
            ? " — the ensemble had him on its podium. It knew."
            : " — 0.8s from the podium."}
        </p>
      )}

      <div className="reveal-actions">
        {onNextRound && (
          <button type="button" className="primary-button next-round" onClick={onNextRound}>
            Next round →
          </button>
        )}
        <button type="button" className="secondary-button" onClick={onOpenEvidence}>
          Open the evidence
        </button>
      </div>
    </section>
  );
}
