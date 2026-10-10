import type { ReactNode } from "react";
import { driverCode, driverName } from "../lib/drivers";
import type { RoundCall, DigestPick } from "../types";

interface ModelCardProps {
  title: string;
  subtitle?: string;
  /** The podium call — the top-3 of a podium distribution, or the player's lock. */
  call: RoundCall | null;
  /** The win pick: driver + probability, from the engine's win distribution. */
  winPick: DigestPick | null;
  /** Finishing positions by driverId — present after the reveal. */
  landed?: Record<string, number> | null;
  /** Emphasis treatment (the player's own card). */
  highlight?: boolean;
  footer?: ReactNode;
}

function LandedMark({ position, slot }: { position: number | null | undefined; slot: number }) {
  if (position == null) return null;
  const exact = position === slot;
  return (
    <span className={`landed-mark${exact ? " is-exact" : ""}`}>
      {exact ? "✓" : "→"} P{position}
    </span>
  );
}

/**
 * One competitor's reveal card: podium call with landed marks and the win
 * pick. Used for the player's lock and for each model + the ensemble.
 */
export function ModelCard({ title, subtitle, call, winPick, landed, highlight = false, footer }: ModelCardProps) {
  const slots: [string, string][] = call
    ? [
        ["P1", call.p1],
        ["P2", call.p2],
        ["P3", call.p3],
      ]
    : [];
  return (
    <article className={`model-card${highlight ? " is-highlight" : ""}`}>
      <header className="model-card-head">
        <h3>{title}</h3>
        {subtitle && <span className="model-card-subtitle">{subtitle}</span>}
      </header>
      {call ? (
        <ol className="model-card-podium">
          {slots.map(([label, driverId], index) => (
            <li key={label}>
              <span className="podium-slot">{label}</span>
              <span className="podium-driver">
                <span className="driver-code">{driverCode(driverId)}</span>
                {driverName(driverId)}
              </span>
              <LandedMark position={landed?.[driverId]} slot={index + 1} />
            </li>
          ))}
        </ol>
      ) : (
        <p className="model-card-empty">No podium call.</p>
      )}
      {winPick && (
        <p className="model-card-win">
          Win call: {driverName(winPick.driverId)} — {Math.round(winPick.probability * 100)}%
        </p>
      )}
      {footer}
    </article>
  );
}
