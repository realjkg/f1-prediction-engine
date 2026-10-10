import { useEffect, useState } from "react";
import { driverCode, driverName } from "../lib/drivers";
import type { ApiError } from "../lib/api";
import type { RoundCall } from "../types";

export const CALL_SHEET_SECONDS = 30;

interface CallSheetViewProps {
  raceName: string;
  season: number;
  round: number;
  /**
   * The field the models scored — the entrant list from the prediction
   * record's distributions, name-sorted. The engine does not serve grid
   * order or form over HTTP, so the sheet honestly offers the field, not
   * a starting grid.
   */
  entrants: string[];
  datasetDigest: string;
  /** True while the engine scores the lock. */
  locking: boolean;
  lockError: ApiError | null;
  onLock: (call: RoundCall) => void;
}

function formatClock(seconds: number): string {
  return `0:${String(seconds).padStart(2, "0")}`;
}

/**
 * The call sheet — "this is the field the machine called." Tap-tap-tap a
 * podium; the 30-second countdown never robs the call (picking stays
 * available at zero; the timer is pressure, not a gate). A failed lock
 * keeps every pick in place and surfaces the engine's typed error.
 */
export function CallSheetView({
  raceName,
  season,
  round,
  entrants,
  datasetDigest,
  locking,
  lockError,
  onLock,
}: CallSheetViewProps) {
  const [picks, setPicks] = useState<string[]>([]);
  const [secondsLeft, setSecondsLeft] = useState(CALL_SHEET_SECONDS);

  useEffect(() => {
    // The countdown is a subscription to the clock, not to app state.
    const timer = window.setInterval(() => {
      setSecondsLeft((current) => Math.max(0, current - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  const togglePick = (driverId: string) => {
    setPicks((current) => {
      if (current.includes(driverId)) {
        return current.filter((picked) => picked !== driverId);
      }
      return current.length < 3 ? [...current, driverId] : current;
    });
  };

  const complete = picks.length === 3;
  const slotOf = (driverId: string) =>
    picks.indexOf(driverId) >= 0 ? `P${picks.indexOf(driverId) + 1}` : null;

  const lock = () => {
    if (!complete || locking) return;
    onLock({
      p1: picks[0],
      p2: picks[1],
      p3: picks[2],
      lockedAt: new Date().toISOString(),
      datasetDigest,
    });
  };

  return (
    <section className="call-sheet" aria-label={`Call sheet for ${raceName}`}>
      <header className="call-sheet-head">
        <p className="call-sheet-kicker">
          {season} round {round}
        </p>
        <h1>{raceName}</h1>
        <p className="call-sheet-frame">
          The field the machine called. No grid order is served — pick your podium.
        </p>
        <p className="call-sheet-timer" aria-live="polite">
          <span className={`timer${secondsLeft <= 10 ? " is-low" : ""}`}>{formatClock(secondsLeft)}</span>
          {secondsLeft === 0 && <span className="timer-note"> — your call stands whenever you're ready</span>}
        </p>
      </header>

      {picks.length > 0 && (
        <ol className="pick-slots" aria-label="Your podium so far">
          {[0, 1, 2].map((index) => (
            <li key={index} className={picks[index] ? "is-filled" : "is-open"}>
              {picks[index] ? `${["P1", "P2", "P3"][index]} ${driverName(picks[index])}` : `${["P1", "P2", "P3"][index]} —`}
            </li>
          ))}
        </ol>
      )}

      {lockError && (
        <div className="engine-error is-inline" role="alert" data-error-code={lockError.code}>
          <p className="engine-error-headline">The engine refused the lock — your picks are intact.</p>
          <p className="engine-error-detail">
            {lockError.code} — {lockError.message}
          </p>
        </div>
      )}

      <ul className="grid-list">
        {entrants.map((driverId) => {
          const slot = slotOf(driverId);
          return (
            <li key={driverId}>
              <button
                type="button"
                className={`grid-row${slot ? " is-picked" : ""}`}
                aria-pressed={slot != null}
                onClick={() => togglePick(driverId)}
              >
                <span className="grid-driver">
                  <span className="driver-code">{driverCode(driverId)}</span>
                  {driverName(driverId)}
                </span>
                {slot && <span className="grid-slot">{slot}</span>}
              </button>
            </li>
          );
        })}
      </ul>

      <button type="button" className="lock-button" disabled={!complete || locking} onClick={lock}>
        {locking ? "SCORING…" : complete ? "LOCK IT" : `Pick ${3 - picks.length} more`}
      </button>
    </section>
  );
}
