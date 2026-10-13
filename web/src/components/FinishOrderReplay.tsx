import { useState } from "react";
import { driverCode, driverName } from "../lib/drivers";
import type { RaceResultView } from "../types";
import "./FinishOrderReplay.css";

interface FinishOrderReplayProps { result: RaceResultView }

/**
 * Ranked finish reveal sourced only from the engine's classified result.
 * Motion duration and lanes are illustrative, never claimed as F1 telemetry.
 */
export function FinishOrderReplay({ result }: FinishOrderReplayProps) {
  const [replay, setReplay] = useState(0);
  const top = result.podium.slice(0, 3);
  if (top.length === 0) return null;

  return (
    <section className="finish-order" aria-label="Game podium animation">
      <div className="finish-order__heading">
        <h2>Race finish reveal</h2>
        <button type="button" className="secondary-button" onClick={() => setReplay((value) => value + 1)}>Replay finish</button>
      </div>
      <p className="finish-order__help">Actual classified podium from the race record. Animation speed is illustrative, not recorded car timing.</p>
      <div key={replay} className="finish-order__scene" role="img" aria-label={"Classified podium: " + top.map((id, index) => "P" + (index + 1) + " " + driverName(id)).join(", ")}>
        {top.map((driver, index) => (
          <div key={driver} className={"finish-order__lane finish-order__lane--" + (index + 1)}>
            <span className="finish-order__place">P{index + 1}</span>
            <span className="finish-order__moving-car" aria-hidden="true" style={{ animationDuration: String(3.6 + index * .65) + "s" }}>
              <svg viewBox="0 0 76 35" focusable="false">
                <rect x="15" y="3" width="14" height="8" rx="2" fill="#0d1015" />
                <rect x="15" y="24" width="14" height="8" rx="2" fill="#0d1015" />
                <rect x="50" y="3" width="15" height="8" rx="2" fill="#0d1015" />
                <rect x="50" y="24" width="15" height="8" rx="2" fill="#0d1015" />
                <path d="M4 15 L18 13 L28 15 L45 15 L52 11 L60 11 L62 16 L72 16 L72 21 L62 21 L60 25 L52 25 L45 20 L28 20 L18 23 L4 21 Z" fill="currentColor" />
                <path d="M20 12 V24 M60 12 V23" stroke="#edf4ff" strokeWidth="3" />
                <path d="M33 15 H44 V20 H33 Z" fill="#15202b" />
              </svg>
            </span>
            <span className="finish-order__label">{driverCode(driver)} <small>{driverName(driver)}</small></span>
          </div>
        ))}
        <div className="finish-order__line" aria-hidden="true" />
      </div>
    </section>
  );
}
