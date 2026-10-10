import { driverName, DRIVERS } from "../fixtures/drivers";
import { topPicks } from "../fixtures/briefs";
import type { CallSheet } from "../fixtures/callsheets";
import { podiumCall, type RoundScore } from "../lib/scoring";
import type { NearMissFeedback } from "../lib/standings";
import type { BadgeId, PredictionRecord, RaceIdentity, RoundCall } from "../types";
import { ConsensusChip } from "./ConsensusChip";
import { Confetti } from "./Confetti";
import { ModelCard } from "./ModelCard";
import { RoundScoreCard } from "./RoundScoreCard";

interface RevealViewProps {
  race: RaceIdentity;
  /** The round's call sheet — carries the classified finishing order. */
  sheet: CallSheet;
  record: PredictionRecord;
  call: RoundCall;
  score: RoundScore;
  streakAfter: number;
  nearMissFeedback: NearMissFeedback | null;
  badgesEarned: BadgeId[];
  /** Null when every round is played — the loop closes on the picker. */
  onNextRound: (() => void) | null;
  onOpenEvidence: () => void;
}

function revealHeadline(score: RoundScore): string {
  if (score.positionExactCount === 3) return "EXACT PODIUM";
  if (score.winnerBonus) return "WINNER CALLED";
  if (score.total > 0) return "ON THE BOARD";
  return "THE MACHINE SAW IT COMING";
}

function ActualPodium({ finishingOrder }: { finishingOrder: string[] }) {
  const top = finishingOrder.slice(0, 3);
  return (
    <ol className="actual-podium">
      {top.map((driverId, index) => (
        <li key={driverId}>
          <span className="podium-slot">P{index + 1}</span>
          <span className="podium-driver">
            <span className="driver-code">{DRIVERS[driverId]?.code}</span>
            {driverName(driverId)}
          </span>
        </li>
      ))}
    </ol>
  );
}

/**
 * The reveal — your call vs the actual result vs every model's card, the
 * round score, and the way back into the loop. The reveal is the dopamine
 * moment: everything renders immediately, animation is CSS-only.
 */
export function RevealView({
  race,
  sheet,
  record,
  call,
  score,
  streakAfter,
  nearMissFeedback,
  badgesEarned,
  onNextRound,
  onOpenEvidence,
}: RevealViewProps) {
  // Finishing positions from the same classified order the scoring used.
  const landed: Record<string, number> = Object.fromEntries(
    sheet.finishingOrder.map((driverId, index) => [driverId, index + 1]),
  );

  return (
    <section className="reveal" aria-label={`Reveal for ${race.name}`}>
      <Confetti show={score.positionExactCount === 3} />
      <header className="reveal-head">
        <p className="reveal-kicker">{race.name}</p>
        <h1 className={`reveal-headline${score.positionExactCount === 3 ? " is-exact" : ""}`}>
          {revealHeadline(score)}
        </h1>
        <ConsensusChip flag={record.ensemble.consensus.flag} coinFlip />
        <p className="reveal-hindsight">Open replay — the models never saw this result; you may remember it.</p>
      </header>

      <section className="actual-result" aria-label="Actual result">
        <h2>Actual podium</h2>
        <ActualPodium finishingOrder={sheet.finishingOrder} />
      </section>

      <div className="reveal-cards">
        <ModelCard
          title="Your call"
          highlight
          call={call}
          winPick={null}
          landed={landed}
          footer={<p className="card-when">Locked {call.lockedAt ?? "—"}</p>}
        />
        <ModelCard
          title="Ensemble"
          subtitle="weighted blend"
          call={podiumCall(record.ensemble.podium)}
          winPick={topPicks(record.ensemble.winner, 1)[0] ?? null}
          landed={landed}
        />
        {(["m1-gbm", "m2-logit", "m3-form"] as const).map((modelId) => (
          <ModelCard
            key={modelId}
            title={modelId}
            call={podiumCall(record.models[modelId].podium)}
            winPick={topPicks(record.models[modelId].winner, 1)[0] ?? null}
            landed={landed}
          />
        ))}
      </div>

      <RoundScoreCard score={score} streakAfter={streakAfter} badgesEarned={badgesEarned} />

      {nearMissFeedback && (
        <p className="near-miss" role="status">
          Your P{nearMissFeedback.pickedSlot} {driverName(nearMissFeedback.driverId)} finished P4
          {nearMissFeedback.ensembleKnew
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
