import { driverCode, driverName } from "../lib/drivers";
import type { DigestPick } from "../types";

interface ProbabilityBarsProps {
  /** A win or podium distribution — driverId -> probability. */
  distribution: Record<string, number>;
  /** How many picks to render (distribution order is meaningless; sorted here). */
  count?: number;
  label?: string;
}

/**
 * Animated probability bars over one engine distribution. Sorted by
 * probability descending — the record's key order carries no meaning.
 */
export function ProbabilityBars({ distribution, count = 3, label }: ProbabilityBarsProps) {
  const picks: DigestPick[] = Object.entries(distribution)
    .map(([driverId, probability]) => ({ driverId, probability }))
    .sort((a, b) => b.probability - a.probability)
    .slice(0, count);
  return (
    <div className="probability-bars" role="img" aria-label={label ?? "Model probabilities"}>
      {picks.map((pick) => (
        <div key={pick.driverId} className="probability-row">
          <span className="probability-driver">
            <span className="driver-code">{driverCode(pick.driverId)}</span>
            {driverName(pick.driverId)}
          </span>
          <span className="probability-track">
            <span className="probability-fill" style={{ width: `${Math.round(pick.probability * 100)}%` }} />
          </span>
          <span className="probability-value">{Math.round(pick.probability * 100)}%</span>
        </div>
      ))}
    </div>
  );
}
