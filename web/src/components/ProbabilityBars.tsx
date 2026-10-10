import { driverName } from "../fixtures/drivers";

export interface ProbabilityBarEntry {
  driverId: string;
  probability: number;
  /** Optional landed marker — the finishing position after the reveal. */
  landed?: number | null;
}

interface ProbabilityBarsProps {
  entries: ProbabilityBarEntry[];
  /** Cap displayed bars; probabilities are already top-N when provided. */
  limit?: number;
  max?: number;
}

/**
 * Animated probability bars — scaleX from 0 to the value on mount (CSS
 * animation, transform-origin left). Honors prefers-reduced-motion via CSS.
 */
export function ProbabilityBars({ entries, limit = 5, max = 1 }: ProbabilityBarsProps) {
  return (
    <ul className="prob-bars">
      {entries.slice(0, limit).map((entry) => (
        <li key={entry.driverId} className="prob-bar-row">
          <span className="prob-bar-driver">{driverName(entry.driverId)}</span>
          <span
            className="prob-bar-track"
            role="meter"
            aria-valuemin={0}
            aria-valuemax={max}
            aria-valuenow={entry.probability}
            aria-label={`${driverName(entry.driverId)} probability ${Math.round(entry.probability * 100)} percent`}
          >
            <span className="prob-bar-fill" style={{ ["--p" as string]: entry.probability / max }} />
          </span>
          <span className="prob-bar-value">{Math.round(entry.probability * 100)}%</span>
          {entry.landed != null && (
            <span className="prob-bar-landed">P{entry.landed}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
