import type { CSSProperties } from "react";
import { formatPercent } from "../lib/baseline";
import { driverCode, driverName } from "../lib/drivers";
import type { DigestPick } from "../types";

interface ProbabilityBarsProps {
  /** A win or podium distribution — driverId -> probability. */
  distribution: Record<string, number>;
  /** How many picks to render (distribution order is meaningless; sorted here). */
  count?: number;
  label?: string;
  /** Fill color for the bars; defaults to the accent. Pair with a text label, never use alone. */
  color?: string;
}

/**
 * Animated probability bars over one engine distribution. Sorted by
 * probability descending — the record's key order carries no meaning.
 *
 * Each row carries its driver and value as text, so the bar never depends on
 * color or length alone, and screen readers hear every row (the container is a
 * labeled list, not an image).
 */
export function ProbabilityBars({ distribution, count = 3, label, color }: ProbabilityBarsProps) {
  const picks: DigestPick[] = Object.entries(distribution)
    .map(([driverId, probability]) => ({ driverId, probability }))
    .sort((a, b) => b.probability - a.probability)
    .slice(0, count);
  return (
    <ul className="prob-bars" aria-label={label ?? "Model probabilities"}>
      {picks.map((pick) => {
        const fillStyle = {
          "--p": Math.max(0, Math.min(1, pick.probability)),
          ...(color ? { background: color } : {}),
        } as CSSProperties;
        return (
          <li key={pick.driverId} className="prob-bar-row">
            <span className="prob-bar-driver">
              <span className="driver-code">{driverCode(pick.driverId)}</span> {driverName(pick.driverId)}
            </span>
            <span className="prob-bar-track" aria-hidden="true">
              <span className="prob-bar-fill" style={fillStyle} />
            </span>
            <span className="prob-bar-value num">{formatPercent(pick.probability)}</span>
          </li>
        );
      })}
    </ul>
  );
}
