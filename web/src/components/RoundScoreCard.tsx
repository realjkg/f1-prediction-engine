import type { BadgeId, RoundCallScore, StreakState } from "../types";
import { BADGES } from "../lib/badges";

interface RoundScoreCardProps {
  /** The engine-computed round score (GET /api/races/{raceId}/score). */
  round: RoundCallScore;
  /** The engine's streak state for this round. */
  streak: StreakState;
  /** Badges earned by this round. */
  badgesEarned: BadgeId[];
}

/** The round's score breakdown — every number engine-served. */
export function RoundScoreCard({ round, streak, badgesEarned }: RoundScoreCardProps) {
  return (
    <section className="score-card" aria-label="Round score">
      <div className="score-total">
        <span className="score-number">+{round.totalPoints}</span>
        <span className="score-unit">pts</span>
        {round.coinFlip && <span className="score-coin">COIN FLIP ×2</span>}
      </div>
      <ul className="score-breakdown">
        {round.picks.map((pick) => (
          <li key={pick.slot} data-outcome={pick.outcome}>
            {pick.slot.toUpperCase()} {pick.driverId} — {pick.outcome.toLowerCase().replace("_", " ")}
            {pick.points > 0 ? ` (+${pick.points})` : ""}
          </li>
        ))}
      </ul>
      <p className="score-streak">
        {streak.flame ? "FLAME " : ""}
        Streak: {streak.after}
        {streak.flame ? " — on fire" : ""}
      </p>
      {badgesEarned.length > 0 && (
        <ul className="score-badges">
          {badgesEarned.map((id) => (
            <li key={id} className="badge-chip" data-badge={id}>
              {BADGES[id].name}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
