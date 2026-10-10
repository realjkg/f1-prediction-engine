import { useEffect, useState } from "react";
import { driverName, DRIVERS } from "../fixtures/drivers";
import type { RoundCall } from "../types";
import type { CallSheet } from "../fixtures/callsheets";

export const CALL_SHEET_SECONDS = 30;

interface CallSheetViewProps {
  raceName: string;
  season: number;
  round: number;
  sheet: CallSheet;
  datasetDigest: string;
  onLock: (call: RoundCall) => void;
}

function formatClock(seconds: number): string {
  return `0:${String(seconds).padStart(2, "0")}`;
}

/**
 * The call sheet — "this is all the machine knows." Tap-tap-tap a podium,
 * 30-second countdown that never robs the call (picking stays available at
 * zero; the timer is pressure, not a gate).
 */
export function CallSheetView({ raceName, season, round, sheet, datasetDigest, onLock }: CallSheetViewProps) {
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
    if (!complete) return;
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
        <p className="call-sheet-frame">This is all the machine knows. Call the podium.</p>
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

      <ul className="grid-list">
        {sheet.qualifying.map((line) => {
          const formLine = sheet.form.find((f) => f.driverId === line.driverId);
          const slot = slotOf(line.driverId);
          return (
            <li key={line.driverId}>
              <button
                type="button"
                className={`grid-row${slot ? " is-picked" : ""}`}
                aria-pressed={slot != null}
                onClick={() => togglePick(line.driverId)}
              >
                <span className="grid-pos">{line.position ?? "—"}</span>
                <span className="grid-driver">
                  <span className="driver-code">{DRIVERS[line.driverId]?.code}</span>
                  {driverName(line.driverId)}
                </span>
                <span className="grid-team">{DRIVERS[line.driverId]?.team}</span>
                <span className="grid-delta">
                  {line.deltaPoleMs == null ? "—" : `+${(line.deltaPoleMs / 1000).toFixed(3)}s`}
                </span>
                <span className="grid-form">
                  {formLine ? formLine.recentFinishes.map((finish, i) => <i key={i}>{finish}</i>) : null}
                </span>
                {slot && <span className="grid-slot">{slot}</span>}
              </button>
            </li>
          );
        })}
      </ul>

      <button type="button" className="lock-button" disabled={!complete} onClick={lock}>
        {complete ? "LOCK IT" : `Pick ${3 - picks.length} more`}
      </button>
    </section>
  );
}
