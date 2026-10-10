import type { BadgeId } from "../types";
import { BADGES } from "../lib/badges";
import { STREAK_FLAME_AT, type RoundScore } from "../lib/scoring";

interface RoundScoreCardProps {
  score: RoundScore;
  /** Streak count after this round's update. */
  streakAfter: number;
  /** Badges earned by this round. */
  badgesEarned: BadgeId[];
}

/** The round's score breakdown — engine rules, locally mirrored. */
export function RoundScoreCard({ score, streakAfter, badgesEarned }: RoundScoreCardProps) {
  return (
    <section className="score-card" aria-label="Round score">
      <div className="score-total">
        <span className="score-number">+{score.total}</span>
        <span className="score-unit">pts</span>
        {score.multiplier > 1 && <span className="score-coin">COIN FLIP ×2</span>}
      </div>
      <ul className="score-breakdown">
        <li>{score.positionExactCount}× position-exact (+{score.positionExactCount * 5})</li>
        {score.winnerBonus && <li>Winner called (+3)</li>}
        {score.nearMissCount > 0 && <li>Near miss P4 (+{score.nearMissCount})</li>}
      </ul>
      <p className="score-streak">
        {streakAfter >= STREAK_FLAME_AT ? "FLAME " : ""}Streak: {streakAfter}
        {streakAfter >= STREAK_FLAME_AT ? " — on fire" : ""}
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
